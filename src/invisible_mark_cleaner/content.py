from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable

import pikepdf
from pikepdf import Array, ContentStreamInstruction, Dictionary, Name, Operator, Stream, String

from .fonts import UNKNOWN_FONT, UNREADABLE, Font, load_font
from .layers import Layers
from .model import Finding, MarkKind

NEAR_WHITE = 0.95       # gray and RGB components at or above this read as white
NO_INK = 0.05           # CMYK components at or below this read as white
INVISIBLE_ALPHA = 0.05  # fill or stroke opacity at or below this reads as invisible
SAMPLE_RISE = 1 / 3     # background sample height above the baseline, in font sizes
APPROX_ADVANCE = 0.5    # glyph advance guess for sample positions only, in font sizes
WORD_GAP = 300          # TJ adjustment, in thousandths of an em, that reads as a space in snippets
SNIPPET_LIMIT = 300

Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]
Box = tuple[float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
UNIT_SQUARE = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
FILLS = {"f", "F", "f*", "B", "B*", "b", "b*"}

COMPONENTS = {"gray": 1, "RGB": 3, "CMYK": 4}
INITIAL = {"gray": (0.0,), "RGB": (0.0, 0.0, 0.0), "CMYK": (0.0, 0.0, 0.0, 1.0)}
WHITE_TESTS = {
    "gray": lambda v: v[0] >= NEAR_WHITE,
    "RGB": lambda v: min(v) >= NEAR_WHITE,
    "CMYK": lambda v: max(v) <= NO_INK,
}
SPACE_MODELS = {
    "/DeviceGray": "gray", "/CalGray": "gray",
    "/DeviceRGB": "RGB", "/CalRGB": "RGB",
    "/DeviceCMYK": "CMYK",
}
ICC_MODELS = {1: "gray", 3: "RGB", 4: "CMYK"}
DEVICE_SETTERS = {"G": "gray", "g": "gray", "RG": "RGB", "rg": "RGB", "K": "CMYK", "k": "CMYK"}
TEXT_STATE = {"Tc": "char_spacing", "Tw": "word_spacing", "TL": "leading", "Ts": "rise"}


@dataclass(frozen=True)
class Colour:
    model: str | None  # None for spaces that cannot be judged: Indexed, Separation, DeviceN, Pattern, Lab
    values: tuple[float, ...] = ()

    def near_white(self) -> bool:
        test = WHITE_TESTS.get(self.model)
        return test is not None and len(self.values) == COMPONENTS[self.model] and test(self.values)

    def describe(self) -> str:
        return " ".join([self.model or "unknown", *(f"{v:.2f}" for v in self.values)])


BLACK = Colour("gray", (0.0,))


@dataclass
class GraphicsState:
    ctm: Matrix = IDENTITY
    fill: Colour = BLACK
    stroke: Colour = BLACK
    fill_alpha: float = 1.0
    stroke_alpha: float = 1.0
    font: Font = UNKNOWN_FONT
    size: float = 0.0
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    scale: float = 1.0
    leading: float = 0.0
    render_mode: int = 0
    rise: float = 0.0


@dataclass
class HiddenSection:
    layer: str
    texts: list[str] = field(default_factory=list)
    painted: bool = False

    def drop(self, *replacement: ContentStreamInstruction) -> list:
        self.painted = True
        return list(replacement)


DROPPED = object()  # marked-content entry for a hidden section nested inside another hidden one


@dataclass
class Frame:
    """One content stream being walked: its resources, state stacks and rewritten output."""

    resources: Dictionary
    gs: GraphicsState
    hidden: HiddenSection | None = None
    stack: list[GraphicsState] = field(default_factory=list)
    sections: list = field(default_factory=list)
    path: list[Point] = field(default_factory=list)
    tm: Matrix = IDENTITY
    tlm: Matrix = IDENTITY
    out: list = field(default_factory=list)
    changed: bool = False


def layer_detail(layer: str) -> str:
    return f"hidden layer '{layer}'"


def classify(gs: GraphicsState, layer: str | None, on_light: Callable[[], bool]) -> tuple[MarkKind, str] | None:
    if layer is not None:
        return MarkKind.HIDDEN_LAYER, layer_detail(layer)
    if gs.render_mode == 3:
        return MarkKind.INVISIBLE_TEXT, "text render mode 3"
    fill, stroke = ("fill", gs.fill, gs.fill_alpha), ("stroke", gs.stroke, gs.stroke_alpha)
    inks = {0: [fill], 1: [stroke], 2: [fill, stroke]}.get(gs.render_mode)
    if inks is None:
        return None
    if all(alpha <= INVISIBLE_ALPHA for _, _, alpha in inks):
        return MarkKind.TRANSPARENT_TEXT, ", ".join(f"{name} opacity {alpha:.2f}" for name, _, alpha in inks)
    # Type 3 glyphs may paint with their own colours, so the fill colour says nothing about them.
    if not gs.font.type3 and all(colour.near_white() for _, colour, _ in inks) and on_light():
        return MarkKind.WHITE_TEXT, ", ".join(f"{name} colour {colour.describe()}" for name, colour, _ in inks)
    return None


class Walker:
    def __init__(self, pdf: pikepdf.Pdf, layers: Layers):
        self.pdf = pdf
        self.layers = layers
        self.fonts: dict[tuple[int, int], Font] = {}
        self.forms_done: set[tuple[int, int]] = set()
        self.forms_open: set[tuple[int, int]] = set()
        self.findings: list[Finding] = []
        self.page = 0
        self.regions: list[tuple[Box | None, bool]] = []

    def clean(self) -> list[Finding]:
        for number, page in enumerate(self.pdf.pages, start=1):
            self.page, self.regions = number, []
            frame = Frame(page.obj.get("/Resources", Dictionary()), GraphicsState())
            if self.run(frame, page.obj):
                page.obj.Contents = self.pdf.make_stream(pikepdf.unparse_content_stream(frame.out))
        return self.findings

    def run(self, frame: Frame, owner: pikepdf.Object) -> bool:
        """Walk one content stream into `frame.out`; True when the output differs from the input."""
        try:
            instructions = pikepdf.parse_content_stream(owner)
        except pikepdf.PdfError:
            return False
        for instruction in instructions:
            op = str(instruction.operator)
            handler = HANDLERS.get(op)
            try:
                result = handler(self, frame, instruction.operands, op) if handler else None
            except (ValueError, TypeError, IndexError, pikepdf.PdfError):
                result = None  # malformed operands or resources: keep the operator untouched
            if result is None:
                frame.out.append(instruction)
            else:
                frame.out.extend(result)
                frame.changed = True
        for entry in frame.sections:
            if isinstance(entry, HiddenSection):
                self.close(entry)
        return frame.changed

    def run_form(self, f: Frame, form: Stream, hidden: HiddenSection | None) -> None:
        """Walk a form XObject. With `hidden`, only collect its text: the caller drops the Do."""
        key = form.objgen
        if key in self.forms_open or (hidden is None and key in self.forms_done):
            return
        resources = form.get("/Resources")
        sub = Frame(
            resources if isinstance(resources, Dictionary) else f.resources,
            replace(f.gs, ctm=mul(matrix(form.get("/Matrix", IDENTITY)), f.gs.ctm)),
            hidden=hidden,
        )
        self.forms_open.add(key)
        changed = self.run(sub, form)
        self.forms_open.discard(key)
        if hidden is None:
            self.forms_done.add(key)
            if changed:
                form.write(pikepdf.unparse_content_stream(sub.out))

    def show(self, f: Frame, items: list, prefix: list) -> list | None:
        gs = f.gs
        runs = [gs.font.split(bytes(item)) if isinstance(item, String) else float(item) for item in items]
        tx, exact = displacement(gs, runs)
        start = mul(f.tm, gs.ctm)
        f.tm = mul((1.0, 0.0, 0.0, 1.0, tx, 0.0), f.tm)
        if not any(isinstance(run, list) and run for run in runs):
            return None
        y = gs.rise + gs.size * SAMPLE_RISE
        on_light = lambda: all(self.is_light(apply(start, x, y)) for x in (0.0, tx / 2, tx))
        verdict = classify(gs, f.hidden.layer if f.hidden else None, on_light)
        if verdict is None:
            return None
        text = decode(gs.font, runs)
        replacement = prefix + blank_advance(gs, runs, tx, exact)
        if f.hidden:
            f.hidden.texts.append(text)
            return f.hidden.drop(*replacement)
        if not text.strip():
            return None
        self.report(*verdict, text)
        return replacement

    def report(self, kind: MarkKind, detail: str, text: str) -> None:
        self.findings.append(Finding(kind, self.page, snippet(text), detail))

    def close(self, section: HiddenSection) -> None:
        if section.painted:
            self.report(MarkKind.HIDDEN_LAYER, layer_detail(section.layer), " ".join(section.texts))

    def font(self, resources: Dictionary, name: Name) -> Font:
        obj = resources.get("/Font", Dictionary()).get(name)
        if not isinstance(obj, Dictionary):
            return UNKNOWN_FONT
        if not obj.is_indirect:
            return load_font(obj)
        if obj.objgen not in self.fonts:
            self.fonts[obj.objgen] = load_font(obj)
        return self.fonts[obj.objgen]

    def paint(self, points: list[Point], light: bool) -> None:
        xs, ys = [x for x, _ in points], [y for _, y in points]
        self.regions.append(((min(xs), min(ys), max(xs), max(ys)), light))

    def is_light(self, point: Point) -> bool:
        """Whether the topmost thing painted so far under `point` is light; bare paper counts as light."""
        x, y = point
        for box, light in reversed(self.regions):
            if box is None or (box[0] <= x <= box[2] and box[1] <= y <= box[3]):
                return light
        return True


def clean_pages(pdf: pikepdf.Pdf, layers: Layers) -> list[Finding]:
    return Walker(pdf, layers).clean()


def displacement(gs: GraphicsState, runs: list) -> tuple[float, bool]:
    """Horizontal text-space advance of a show, and whether it is exact (every glyph width known)."""
    tx, exact = 0.0, True
    for run in runs:
        if isinstance(run, float):
            tx -= run / 1000 * gs.size * gs.scale
            continue
        for code in run:
            width = gs.font.advance(code)
            exact = exact and width is not None
            spacing = gs.char_spacing + (gs.word_spacing if code == b" " else 0.0)
            tx += ((APPROX_ADVANCE if width is None else width) * gs.size + spacing) * gs.scale
    return tx, exact


def blank_advance(gs: GraphicsState, runs: list, tx: float, exact: bool) -> list:
    """A glyph-free TJ that moves the text position as the removed show did (only its own numbers if widths are unknown)."""
    unit = gs.size * gs.scale
    n = -tx * 1000 / unit if exact and unit else sum(run for run in runs if isinstance(run, float))
    return [instruction("TJ", Array([n]))] if n else []


def decode(font: Font, runs: list) -> str:
    parts = []
    for run in runs:
        if isinstance(run, list):
            parts += [font.text(code) for code in run]
        elif run <= -WORD_GAP:
            parts.append(" ")
    return "".join(parts)


def snippet(text: str) -> str:
    text = " ".join("".join(ch for ch in text if ch != UNREADABLE and (ch.isprintable() or ch.isspace())).split())
    return text if len(text) <= SNIPPET_LIMIT else text[:SNIPPET_LIMIT - 1] + "…"


def colour_model(space: object, resources: Dictionary) -> str | None:
    if isinstance(space, Name) and str(space) not in SPACE_MODELS:
        space = resources.get("/ColorSpace", Dictionary()).get(space)
    if isinstance(space, Array) and len(space):
        if space[0] == Name.ICCBased and len(space) > 1 and isinstance(space[1], Stream):
            return ICC_MODELS.get(int(space[1].get("/N", 0)))
        return SPACE_MODELS.get(str(space[0]))
    return SPACE_MODELS.get(str(space)) if isinstance(space, Name) else None


def set_colour(gs: GraphicsState, op: str, colour: Colour) -> None:
    if op[0].isupper():
        gs.stroke = colour
    else:
        gs.fill = colour


def next_line(f: Frame, tx: float, ty: float) -> None:
    f.tm = f.tlm = mul((1.0, 0.0, 0.0, 1.0, tx, ty), f.tlm)


def mul(m: Matrix, n: Matrix) -> Matrix:
    a, b, c, d, e, g = m
    p, q, r, s, t, u = n
    return (a * p + b * r, a * q + b * s, c * p + d * r, c * q + d * s, e * p + g * r + t, e * q + g * s + u)


def apply(m: Matrix, x: float, y: float) -> Point:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def matrix(values: object) -> Matrix:
    a, b, c, d, e, f = (float(v) for v in values)
    return (a, b, c, d, e, f)


def transformed(m: Matrix, points: tuple[Point, ...]) -> list[Point]:
    return [apply(m, x, y) for x, y in points]


def instruction(op: str, *operands: object) -> ContentStreamInstruction:
    return ContentStreamInstruction(list(operands), Operator(op))


Handler = Callable[[Walker, Frame, list, str], "list | None"]
HANDLERS: dict[str, Handler] = {}


def handles(*operators: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        HANDLERS.update(dict.fromkeys(operators, handler))
        return handler
    return register


@handles("q")
def save_state(w: Walker, f: Frame, args: list, op: str) -> None:
    f.stack.append(replace(f.gs))


@handles("Q")
def restore_state(w: Walker, f: Frame, args: list, op: str) -> None:
    if f.stack:
        f.gs = f.stack.pop()


@handles("cm")
def concat_matrix(w: Walker, f: Frame, args: list, op: str) -> None:
    f.gs.ctm = mul(matrix(args), f.gs.ctm)


@handles("gs")
def ext_gstate(w: Walker, f: Frame, args: list, op: str) -> None:
    ext = f.resources.get("/ExtGState", Dictionary()).get(args[0])
    if isinstance(ext, Dictionary):
        f.gs.fill_alpha = float(ext.get("/ca", f.gs.fill_alpha))
        f.gs.stroke_alpha = float(ext.get("/CA", f.gs.stroke_alpha))


@handles("CS", "cs")
def colour_space(w: Walker, f: Frame, args: list, op: str) -> None:
    model = colour_model(args[0], f.resources)
    set_colour(f.gs, op, Colour(model, INITIAL.get(model, ())))


@handles("SC", "SCN", "sc", "scn")
def colour(w: Walker, f: Frame, args: list, op: str) -> None:
    current = f.gs.stroke if op[0].isupper() else f.gs.fill
    model = None if args and isinstance(args[-1], Name) else current.model
    set_colour(f.gs, op, Colour(model, tuple(float(a) for a in args if not isinstance(a, Name))))


@handles(*DEVICE_SETTERS)
def device_colour(w: Walker, f: Frame, args: list, op: str) -> None:
    set_colour(f.gs, op, Colour(DEVICE_SETTERS[op], tuple(float(a) for a in args)))


@handles(*TEXT_STATE)
def text_state(w: Walker, f: Frame, args: list, op: str) -> None:
    setattr(f.gs, TEXT_STATE[op], float(args[0]))


@handles("Tz")
def horizontal_scale(w: Walker, f: Frame, args: list, op: str) -> None:
    f.gs.scale = float(args[0]) / 100


@handles("Tr")
def render_mode(w: Walker, f: Frame, args: list, op: str) -> None:
    f.gs.render_mode = int(args[0])


@handles("Tf")
def set_font(w: Walker, f: Frame, args: list, op: str) -> None:
    f.gs.font = w.font(f.resources, args[0])
    f.gs.size = float(args[1])


@handles("BT")
def begin_text(w: Walker, f: Frame, args: list, op: str) -> None:
    f.tm = f.tlm = IDENTITY


@handles("Td")
def move_text(w: Walker, f: Frame, args: list, op: str) -> None:
    next_line(f, float(args[0]), float(args[1]))


@handles("TD")
def move_text_set_leading(w: Walker, f: Frame, args: list, op: str) -> None:
    f.gs.leading = -float(args[1])
    next_line(f, float(args[0]), float(args[1]))


@handles("Tm")
def set_text_matrix(w: Walker, f: Frame, args: list, op: str) -> None:
    f.tm = f.tlm = matrix(args)


@handles("T*")
def next_text_line(w: Walker, f: Frame, args: list, op: str) -> None:
    next_line(f, 0.0, -f.gs.leading)


@handles("Tj")
def show_string(w: Walker, f: Frame, args: list, op: str) -> list | None:
    return w.show(f, [args[0]], [])


@handles("TJ")
def show_array(w: Walker, f: Frame, args: list, op: str) -> list | None:
    return w.show(f, list(args[0]), [])


@handles("'")
def next_line_show(w: Walker, f: Frame, args: list, op: str) -> list | None:
    next_line(f, 0.0, -f.gs.leading)
    return w.show(f, [args[0]], [instruction("T*")])


@handles('"')
def spaced_next_line_show(w: Walker, f: Frame, args: list, op: str) -> list | None:
    aw, ac, string = args
    f.gs.word_spacing, f.gs.char_spacing = float(aw), float(ac)
    next_line(f, 0.0, -f.gs.leading)
    return w.show(f, [string], [instruction("Tw", aw), instruction("Tc", ac), instruction("T*")])


@handles("m", "l", "c", "v", "y")
def path_points(w: Walker, f: Frame, args: list, op: str) -> None:
    values = [float(a) for a in args]
    f.path += transformed(f.gs.ctm, tuple(zip(values[::2], values[1::2])))


@handles("re")
def rectangle(w: Walker, f: Frame, args: list, op: str) -> None:
    x, y, width, height = (float(a) for a in args)
    f.path += transformed(f.gs.ctm, ((x, y), (x + width, y), (x, y + height), (x + width, y + height)))


@handles("S", "s", "n", *FILLS)
def paint_path(w: Walker, f: Frame, args: list, op: str) -> list | None:
    points, f.path = f.path, []
    if op == "n":
        return None
    if f.hidden:
        # `n` still ends the path, so a pending W clip keeps applying to what follows.
        return f.hidden.drop(instruction("n"))
    if op in FILLS and points:
        w.paint(points, f.gs.fill.near_white())
    return None


@handles("Do")
def draw_xobject(w: Walker, f: Frame, args: list, op: str) -> list | None:
    xobject = f.resources.get("/XObject", Dictionary()).get(args[0])
    if not isinstance(xobject, Stream):
        return None
    form = xobject.get("/Subtype") == Name.Form
    oc = xobject.get("/OC")
    layer = w.layers.hidden_name(oc) if isinstance(oc, Dictionary) else None
    if f.hidden is None and layer is None:
        if form:
            w.run_form(f, xobject, None)
        else:
            w.paint(transformed(f.gs.ctm, UNIT_SQUARE), light=False)
        return None
    section = f.hidden or HiddenSection(layer)
    if form:
        w.run_form(f, xobject, section)
    dropped = section.drop()
    if f.hidden is None:
        w.close(section)
    return dropped


@handles("INLINE IMAGE")
def inline_image(w: Walker, f: Frame, args: list, op: str) -> list | None:
    if f.hidden:
        return f.hidden.drop()
    w.paint(transformed(f.gs.ctm, UNIT_SQUARE), light=False)
    return None


@handles("sh")
def shading(w: Walker, f: Frame, args: list, op: str) -> list | None:
    if f.hidden:
        return f.hidden.drop()
    w.regions.append((None, False))
    return None


@handles("BMC")
def begin_marked_content(w: Walker, f: Frame, args: list, op: str) -> None:
    f.sections.append(None)


@handles("BDC")
def begin_marked_content_with_properties(w: Walker, f: Frame, args: list, op: str) -> list | None:
    tag, props = args
    if isinstance(props, Name):
        props = f.resources.get("/Properties", Dictionary()).get(props)
    layer = w.layers.hidden_name(props) if tag == Name.OC and isinstance(props, Dictionary) else None
    if layer is None:
        f.sections.append(None)
        return None
    if f.hidden:
        f.sections.append(DROPPED)
    else:
        f.hidden = HiddenSection(layer)
        f.sections.append(f.hidden)
    return []


@handles("EMC")
def end_marked_content(w: Walker, f: Frame, args: list, op: str) -> list | None:
    if not f.sections:
        return None
    entry = f.sections.pop()
    if entry is None:
        return None
    if entry is f.hidden:
        w.close(entry)
        f.hidden = None
    return []
