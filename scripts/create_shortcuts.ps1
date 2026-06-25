# Creates/refreshes TermScope shortcuts and stamps them with the app's
# AppUserModelID so the taskbar groups the running window under the pinned icon
# (instead of a separate "python (windowed)" button).
# Run:  powershell -ExecutionPolicy Bypass -File scripts\create_shortcuts.ps1
$ErrorActionPreference = "Stop"

# MUST match APP_AUMID in src/termscope/app.py
$AUMID = "TermScope.App"

# This script lives in <proj>\scripts, so the project root is its parent's parent.
$proj = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
$pyw  = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pyw) {
    $py = (Get-Command python).Source
    $cand = $py -replace 'python\.exe$', 'pythonw.exe'
    $pyw = if (Test-Path $cand) { $cand } else { $py }
}
$icon   = Join-Path $proj "assets\termscope.ico"
$target = Join-Path $proj "TermScope.pyw"

# --- C# helper to write System.AppUserModel.ID onto a .lnk via the shell prop store ---
if (-not ("TS.Aumid" -as [type])) {
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace TS {
  public static class Aumid {
    [DllImport("shell32.dll")]
    static extern int SHGetPropertyStoreFromParsingName(
        [MarshalAs(UnmanagedType.LPWStr)] string pszPath, IntPtr pbc, int flags,
        ref Guid riid, out IPropertyStore ppv);
    [StructLayout(LayoutKind.Sequential)]
    struct PROPERTYKEY { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Sequential)]
    struct PROPVARIANT { public ushort vt; ushort r1; ushort r2; ushort r3; public IntPtr p; public IntPtr p2; }
    [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
      int GetCount(out uint c);
      int GetAt(uint i, out PROPERTYKEY pkey);
      int GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
      int SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
      int Commit();
    }
    public static void Set(string path, string aumid) {
      Guid iid = new Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99");
      IPropertyStore store;
      int hr = SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 0x2, ref iid, out store);
      if (hr != 0) throw new Exception("open store hr=" + hr);
      PROPERTYKEY key = new PROPERTYKEY();
      key.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
      key.pid = 5;
      PROPVARIANT pv = new PROPVARIANT();
      pv.vt = 31; // VT_LPWSTR
      pv.p = Marshal.StringToCoTaskMemUni(aumid);
      store.SetValue(ref key, ref pv);   // store makes its own copy
      store.Commit();
      Marshal.FreeCoTaskMem(pv.p);
      Marshal.ReleaseComObject(store);
    }
  }
}
"@
}

function Set-Aumid($path, $id) {
    try { [TS.Aumid]::Set($path, $id); Write-Output "  AUMID set on: $path" }
    catch { Write-Output "  (could not set AUMID on $path : $_)" }
}

# --- Create/refresh the Start Menu + Desktop shortcuts ---
$dests = @(
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\TermScope.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "TermScope.lnk")
)
$ws = New-Object -ComObject WScript.Shell
foreach ($dest in $dests) {
    $sc = $ws.CreateShortcut($dest)
    $sc.TargetPath       = $pyw
    $sc.Arguments        = '"' + $target + '"'
    $sc.WorkingDirectory = $proj
    $sc.IconLocation     = $icon
    $sc.Description       = "TermScope - live jargon explainer"
    $sc.WindowStyle       = 1
    $sc.Save()
    Write-Output "created: $dest"
    Set-Aumid $dest $AUMID
}

# --- Also stamp any already-pinned taskbar shortcut(s) for TermScope ---
$pinDir = Join-Path $env:APPDATA "Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
if (Test-Path $pinDir) {
    Get-ChildItem $pinDir -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        $sc = $ws.CreateShortcut($_.FullName)
        if ($sc.TargetPath -like '*pythonw*' -and $sc.Arguments -like '*TermScope.pyw*') {
            $sc.IconLocation = $icon; $sc.Save()
            Write-Output "pinned shortcut: $($_.FullName)"
            Set-Aumid $_.FullName $AUMID
        }
    }
}

Write-Output "launcher: $pyw"
Write-Output "AUMID: $AUMID"
Write-Output "Done. If a stray 'python' button lingers, unpin & re-pin TermScope once."
