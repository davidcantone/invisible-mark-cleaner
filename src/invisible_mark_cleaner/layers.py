from __future__ import annotations

import pikepdf
from pikepdf import Array, Dictionary, Name, Stream

ObjGen = tuple[int, int]

POLICIES = {
    "/AnyOn": any,
    "/AllOn": all,
    "/AnyOff": lambda on: not all(on),
    "/AllOff": lambda on: not any(on),
}
CONFIG_ARRAYS = ("/ON", "/OFF", "/Locked", "/Order", "/RBGroups")


class Layers:
    """Optional content visibility from the default configuration, and the groups content depends on."""

    def __init__(self, pdf: pikepdf.Pdf):
        props = pdf.Root.get("/OCProperties")
        self.hidden = hidden_groups(props) if isinstance(props, Dictionary) else set()
        self.stripped: set[ObjGen] = set()
        self.kept: set[ObjGen] = set()

    def hidden_name(self, oc: Dictionary) -> str | None:
        """The layer name when `oc` (an OCG or OCMD) hides its content, else None."""
        groups = member_groups(oc)
        if not self.hides(oc, groups):
            self.kept.update(g.objgen for g in groups)
            return None
        hidden = [g for g in groups if g.objgen in self.hidden]
        self.stripped.update(g.objgen for g in hidden)
        return ", ".join(str(g.get("/Name", "unnamed")) for g in hidden or groups)

    def hides(self, oc: Dictionary, groups: list[Dictionary]) -> bool:
        if oc.get("/Type") != Name.OCMD:
            return oc.objgen in self.hidden
        if "/VE" in oc or not groups:
            return False
        policy = POLICIES.get(str(oc.get("/P", "/AnyOn")), any)
        return not policy([g.objgen not in self.hidden for g in groups])

    def prune(self, pdf: pikepdf.Pdf) -> None:
        """Drop stripped hidden groups from /OCProperties unless something left in the file still uses them."""
        doomed = self.stripped - self.kept
        if doomed:
            doomed -= annotation_groups(pdf)
        if not doomed:
            return
        props = pdf.Root.OCProperties
        if "/OCGs" in props:
            props.OCGs = without(props.OCGs, doomed)
        for config in [props.get("/D"), *props.get("/Configs", [])]:
            if not isinstance(config, Dictionary):
                continue
            for key in CONFIG_ARRAYS:
                if isinstance(config.get(key), Array):
                    config[key] = without(config[key], doomed)
            for usage in config.get("/AS", []):
                if isinstance(usage, Dictionary) and isinstance(usage.get("/OCGs"), Array):
                    usage.OCGs = without(usage.OCGs, doomed)


def hidden_groups(props: Dictionary) -> set[ObjGen]:
    config = props.get("/D", Dictionary())
    if config.get("/BaseState") == Name.OFF:
        return objgens(props.get("/OCGs", [])) - objgens(config.get("/ON", []))
    return objgens(config.get("/OFF", []))


def objgens(items: Array) -> set[ObjGen]:
    return {g.objgen for g in items if isinstance(g, Dictionary)}


def member_groups(oc: Dictionary) -> list[Dictionary]:
    if oc.get("/Type") != Name.OCMD:
        return [oc]
    members = oc.get("/OCGs", [])
    members = members if isinstance(members, Array) else [members]
    return [g for g in members if isinstance(g, Dictionary)]


def without(items: Array, doomed: set[ObjGen]) -> Array:
    kept = []
    for item in items:
        if isinstance(item, Array):
            inner = without(item, doomed)
            if len(inner):
                kept.append(inner)
        elif not (isinstance(item, Dictionary) and item.objgen in doomed):
            kept.append(item)
    return Array(kept)


def annotation_groups(pdf: pikepdf.Pdf) -> set[ObjGen]:
    """Groups reachable from annotation /OC entries and appearance streams, which the cleaner never rewrites."""
    found, seen = set(), set()
    stack = [annot.get(key) for page in pdf.pages for annot in page.obj.get("/Annots", [])
             if isinstance(annot, Dictionary) for key in ("/OC", "/AP")]
    while stack:
        obj = stack.pop()
        if isinstance(obj, Array):
            stack.extend(obj)
            continue
        if not isinstance(obj, (Dictionary, Stream)):
            continue
        if obj.is_indirect:
            if obj.objgen in seen:
                continue
            seen.add(obj.objgen)
        if obj.get("/Type") == Name.OCG:
            found.add(obj.objgen)
        else:
            stack.extend(value for _, value in obj.items())
    return found
