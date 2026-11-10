"""Lettering in the 3D view that stays readable — shared by the
variable highlight's names and the face marks. GUI-only.
"""

from __future__ import annotations

_UPRIGHT_BAND = 0.2             # of the screen direction: "near upright"


def upright(_data, action):
    """An `SoCallback` that turns lettering end for end when it would
    read right to left — from the far side of a beam it would otherwise
    be upside down. Runs on each draw, in the text's own frame: its
    baseline is local +X and it faces local +Z, so a half turn about
    local Z keeps it facing the same way and puts the baseline left to
    right. Place the callback where that half turn should pivot."""
    from pivy import coin
    if not action.isOfType(coin.SoGLRenderAction.getClassTypeId()):
        return
    state = action.getState()
    model = coin.SoModelMatrixElement.get(state)
    view = coin.SoViewingMatrixElement.get(state)
    baseline = view.multDirMatrix(model.multDirMatrix(coin.SbVec3f(1, 0, 0)))
    x, y, _z = baseline.getValue()
    size = (x * x + y * y) ** 0.5
    if size < 1e-12:
        return                       # end on: nothing to read anyway
    x, y = x / size, y / size
    # near upright (a post) it reads bottom to top, either way up; the
    # band keeps float noise from flipping it as the view turns
    if x < -_UPRIGHT_BAND or (abs(x) <= _UPRIGHT_BAND and y < 0):
        coin.SoModelMatrixElement.rotateBy(
            state, None, coin.SbRotation(coin.SbVec3f(0, 0, 1), 3.141592653589793))


_LEVEL_BIAS = 1.15              # how much more level a quarter turn must
                                # read before it is taken: no flicker at 45°


def level(_data, action):
    """An `SoCallback` that turns short lettering — a face mark's "+X",
    an "A" — in quarter turns about the way it faces, so its baseline
    runs as near left to right on screen as it can. Lettering that fits
    its face either way (`upright` only turns end for end, for a name
    too long to run across a timber): along a beam it reads along the
    beam, and on a post it reads across the post instead of up it. Same
    frame and placement as `upright`."""
    from pivy import coin
    if not action.isOfType(coin.SoGLRenderAction.getClassTypeId()):
        return
    state = action.getState()
    model = coin.SoModelMatrixElement.get(state)
    view = coin.SoViewingMatrixElement.get(state)

    def screen(v):
        x, y, _z = view.multDirMatrix(model.multDirMatrix(v)).getValue()
        size = (x * x + y * y) ** 0.5
        return (x / size, y / size) if size > 1e-12 else (0.0, 0.0)

    along, across = screen(coin.SbVec3f(1, 0, 0)), screen(coin.SbVec3f(0, 1, 0))
    # quarter turns: 0 keeps local +X as the baseline, 1 takes local +Y,
    # 2 local -X, 3 local -Y — the one pointing most to the screen's right
    rightward = (along[0], across[0], -along[0], -across[0])
    turns = 0 if along[0] >= 0 else 2
    other = 1 if across[0] >= 0 else 3
    if rightward[other] > rightward[turns] * _LEVEL_BIAS:
        turns = other
    if turns:
        coin.SoModelMatrixElement.rotateBy(
            state, None,
            coin.SbRotation(coin.SbVec3f(0, 0, 1), turns * 1.5707963267948966))
