# Auto-enable the BentWizard EnforceNaming macro at FreeCAD GUI startup.
#
# The macro itself lives in the BentWizard repo (single source of truth —
# edits there take effect on the next FreeCAD start). This shim only execs
# it once the event loop is running.
#
# FreeCAD quirks this file works around:
#   - InitGui.py is exec'd, not imported: __file__ is NOT defined here,
#     so the macro path is spelled out explicitly.
#   - InitGui.py's top-level names land in the exec scope's *locals*, but
#     functions defined here resolve names against globals at call time —
#     so the deferred function must be fully self-contained (a top-level
#     constant would raise NameError when the timer fires).
#   - During InitGui execution the main window isn't up yet, so the macro
#     is deferred via QTimer.singleShot until the event loop starts.


def _bw_enforce_naming_autostart():
    import os
    import FreeCAD as App

    _ENFORCE_NAMING_MACRO = (
        r"C:\Users\Adam\Documents\Projects\BentWizard"
        r"\devBuildMacros\EnforceNaming.FCMacro"
    )

    try:
        if not App.GuiUp:
            return
        if getattr(App, "_bentwizard_enforce_naming", None) is not None:
            return  # already enabled this session
        if not os.path.isfile(_ENFORCE_NAMING_MACRO):
            App.Console.PrintWarning(
                "EnforceNaming autostart: macro not found at %s\n"
                % _ENFORCE_NAMING_MACRO)
            return
        with open(_ENFORCE_NAMING_MACRO, encoding="utf-8") as f:
            code = f.read()
        exec(compile(code, _ENFORCE_NAMING_MACRO, "exec"),
             {"__name__": "EnforceNaming"})
    except Exception as exc:
        App.Console.PrintWarning("EnforceNaming autostart failed: %s\n" % exc)


try:
    from PySide import QtCore
    QtCore.QTimer.singleShot(0, _bw_enforce_naming_autostart)
except Exception as _exc:
    import FreeCAD as App
    App.Console.PrintWarning(
        "EnforceNaming autostart could not schedule: %s\n" % _exc)
