<#
.SYNOPSIS
    Point FreeCAD's BentWizard dev-install junction at a chosen checkout.

.DESCRIPTION
    FreeCAD loads the workbench live from a directory junction:

        %APPDATA%\FreeCAD\<version>\Mod\BentWizard  ->  a repo checkout

    A junction targets exactly one directory, so only one git worktree
    (or the main checkout) is "live" in FreeCAD at a time. This script
    swaps the target *safely* — it removes only the reparse point, never
    the target's contents (`rmdir` on a junction unlinks it without
    recursing) — so you can GUI-test the branch you are working on, then
    point back to the main checkout.

    Restart FreeCAD after switching: it caches imported Python modules,
    so a running instance keeps the old code until relaunched.

.PARAMETER Target
    Which checkout to make live. Accepts:
        here         the worktree this script lives in (the branch under test)
        main         the primary/main git worktree
        <a path>     an explicit repo or worktree root
    Omit to just report the current junction target and the worktrees.

.PARAMETER FreeCadVersion
    FreeCAD config folder under %APPDATA%\FreeCAD (default: v1-1).

.EXAMPLE
    .\scripts\dev-install.ps1 here     # test the current worktree branch
    .\scripts\dev-install.ps1 main     # back to the main checkout
    .\scripts\dev-install.ps1          # show current target + worktrees
#>
[CmdletBinding()]
param(
    [string]$Target,
    [string]$FreeCadVersion = "v1-1"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$link = Join-Path $env:APPDATA "FreeCAD\$FreeCadVersion\Mod\BentWizard"

function Get-CurrentTarget {
    if (Test-Path $link) { (Get-Item $link -Force).Target } else { $null }
}

function Get-MainWorktree {
    # `git worktree list --porcelain` lists the primary worktree first.
    $line = git -C $scriptDir worktree list --porcelain |
        Where-Object { $_ -like 'worktree *' } | Select-Object -First 1
    if (-not $line) { throw "Could not determine the main worktree via git." }
    ($line -replace '^worktree ', '').Trim()
}

# --- no argument: report status and exit --------------------------------
if (-not $Target) {
    $cur = Get-CurrentTarget
    if ($cur) { "Junction: $link`n     -> $cur" }
    else      { "Junction not present: $link" }
    ""
    "Worktrees (git):"
    git -C $scriptDir worktree list
    "`nRe-point with:  .\scripts\dev-install.ps1 here | main | <path>"
    return
}

# --- resolve the destination --------------------------------------------
switch ($Target.ToLower()) {
    "here"  { $dest = (git -C $scriptDir rev-parse --show-toplevel) }
    "main"  { $dest = Get-MainWorktree }
    default { $dest = $Target }
}
$dest = (Resolve-Path -LiteralPath $dest).Path   # normalize to a real path

# sanity: the destination must actually be a BentWizard checkout
$probe = Join-Path $dest "freecad\bentwizard\init_gui.py"
if (-not (Test-Path -LiteralPath $probe)) {
    throw "Not a BentWizard checkout (missing $probe): $dest"
}

# --- swap the junction ---------------------------------------------------
if ((Get-CurrentTarget) -and ((Resolve-Path -LiteralPath (Get-CurrentTarget)).Path -eq $dest)) {
    "Already pointing there: $dest"
    return
}

if (Test-Path $link) {
    cmd /c rmdir "$link"                     # unlink only — never deletes the target
    if (Test-Path $link) {
        throw "Could not remove the existing junction (is FreeCAD open and " +
              "holding it? close FreeCAD and retry): $link"
    }
}

$modDir = Split-Path -Parent $link
if (-not (Test-Path $modDir)) { New-Item -ItemType Directory -Path $modDir -Force | Out-Null }

New-Item -ItemType Junction -Path $link -Target $dest | Out-Null

"Dev-install junction updated:"
"  $link"
"     -> $((Get-Item $link -Force).Target)"
"Restart FreeCAD to load this checkout."
