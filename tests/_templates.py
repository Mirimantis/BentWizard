"""Test-only joint templates, authored with the library build script's
own helpers. Import after FreeCAD (see `_repo_path`)."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_library_module():
    """scripts/build_library.py as a module, for its authoring helpers."""
    path = REPO_ROOT / "scripts" / "build_library.py"
    spec = importlib.util.spec_from_file_location("build_library", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def datum_sized_housing(out_dir):
    """Joint_Housing.FCStd in `out_dir`: a housing cut in the host, as
    wide and long as the mate's section and a fixed 1/2 in deep. Its
    component reads ONLY the accessors — no joint parameter — so after
    Apply it names the accessor VarSet and never the joint VarSet. The
    one parameter, `Shrinkage`, is a Float carried as schedule data.
    Returns the file's path."""
    import FreeCAD as App
    from freecad.bentwizard import component, naming
    bl = build_library_module()
    doc = App.newDocument("HousingTemplate")
    try:
        post, _girt, host, _mate, vs = bl.skeleton(doc, "Housing", handed=False)
        J = f"<<{vs.Label}>>"
        bl.add_param(vs, "Shrinkage", "App::PropertyFloat", 0.04,
                     "Expected shrinkage across the grain, as a fraction — "
                     "schedule data only.")
        cutter = component.new_component(
            doc, naming.component_label("Housing", "Housing", naming.TEMPLATE_SERIAL),
            naming.COMPONENT_CUTTER, 1, vs, host)
        component.add_prism(cutter, "HousingPrism", J + ".MateWidthU",
                            J + ".MateWidthV", "0.5 in", direction=-1)
        doc.recompute()
        component.apply_boolean(post, cutter, naming.COMPONENT_CUTTER,
                                naming.boolean_label(naming.COMPONENT_CUTTER,
                                                     cutter.Label))
        doc.recompute()
        path = Path(out_dir) / "Joint_Housing.FCStd"
        doc.saveAs(str(path))
    finally:
        App.closeDocument(doc.Name)
    return path
