//! What is on screen right now: the foreground window's process and how long the user
//! has been idle. Windows only; elsewhere everything is `None` (macOS is a later step).

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Foreground {
    /// Executable file name as Windows reports it, e.g. `VALORANT-Win64-Shipping.exe`.
    pub exe: String,
    /// Full path when the process could be opened (needed for the display name).
    pub path: Option<String>,
}

/// File name without `.exe`, for when the binary has no description.
pub fn exe_stem(exe: &str) -> &str {
    let len = exe.len();
    if len > 4 && exe[len - 4..].eq_ignore_ascii_case(".exe") {
        &exe[..len - 4]
    } else {
        exe
    }
}

#[cfg(windows)]
pub use imp::{app_description, current, idle_seconds};

#[cfg(not(windows))]
pub fn current() -> Option<Foreground> {
    None
}

#[cfg(not(windows))]
pub fn idle_seconds() -> Option<u64> {
    None
}

#[cfg(not(windows))]
pub fn app_description(_path: &str) -> Option<String> {
    None
}

#[cfg(windows)]
mod imp {
    use super::Foreground;
    use std::ffi::c_void;
    use std::path::Path;
    use std::ptr::null_mut;
    use windows_sys::core::BOOL;
    use windows_sys::Win32::Foundation::{CloseHandle, HWND, INVALID_HANDLE_VALUE, LPARAM};
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileVersionInfoSizeW, GetFileVersionInfoW, VerQueryValueW,
    };
    use windows_sys::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
        TH32CS_SNAPPROCESS,
    };
    use windows_sys::Win32::System::SystemInformation::GetTickCount;
    use windows_sys::Win32::System::Threading::{
        OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumChildWindows, GetForegroundWindow, GetWindowThreadProcessId,
    };

    /// UWP apps (Settings, Calculator, …) run inside this host; the real app is a child.
    const UWP_HOST: &str = "ApplicationFrameHost.exe";

    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain(Some(0)).collect()
    }

    fn from_wide(buf: &[u16]) -> String {
        let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
        String::from_utf16_lossy(&buf[..end])
    }

    fn pid_of(hwnd: HWND) -> u32 {
        let mut pid = 0u32;
        // SAFETY: hwnd may be stale; the call then just returns 0.
        unsafe { GetWindowThreadProcessId(hwnd, &mut pid) };
        pid
    }

    fn image_path(pid: u32) -> Option<String> {
        // SAFETY: plain Win32 calls; the handle is closed before returning.
        unsafe {
            let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if process.is_null() {
                return None;
            }
            let mut buf = [0u16; 1024];
            let mut len = buf.len() as u32;
            let ok = QueryFullProcessImageNameW(process, 0, buf.as_mut_ptr(), &mut len);
            CloseHandle(process);
            (ok != 0).then(|| String::from_utf16_lossy(&buf[..len as usize]))
        }
    }

    /// Exe name from a process snapshot: works even when the process can't be opened
    /// (protected / anti-cheat processes).
    fn snapshot_exe(pid: u32) -> Option<String> {
        // SAFETY: the snapshot handle is closed before returning.
        unsafe {
            let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if snapshot == INVALID_HANDLE_VALUE {
                return None;
            }
            let mut entry = PROCESSENTRY32W {
                dwSize: size_of::<PROCESSENTRY32W>() as u32,
                ..Default::default()
            };
            let mut found = None;
            let mut more = Process32FirstW(snapshot, &mut entry) != 0;
            while more {
                if entry.th32ProcessID == pid {
                    found = Some(from_wide(&entry.szExeFile));
                    break;
                }
                more = Process32NextW(snapshot, &mut entry) != 0;
            }
            CloseHandle(snapshot);
            found
        }
    }

    fn describe(pid: u32) -> Option<Foreground> {
        if pid == 0 {
            return None;
        }
        match image_path(pid) {
            Some(path) => {
                let exe = Path::new(&path).file_name()?.to_string_lossy().into_owned();
                Some(Foreground {
                    exe,
                    path: Some(path),
                })
            }
            None => snapshot_exe(pid).map(|exe| Foreground { exe, path: None }),
        }
    }

    struct ChildSearch {
        host_pid: u32,
        found: u32,
    }

    unsafe extern "system" fn find_foreign_child(hwnd: HWND, lparam: LPARAM) -> BOOL {
        // SAFETY: lparam is the &mut ChildSearch passed to EnumChildWindows below.
        let search = unsafe { &mut *(lparam as *mut ChildSearch) };
        let pid = pid_of(hwnd);
        if pid != 0 && pid != search.host_pid {
            search.found = pid;
            return 0; // stop
        }
        1
    }

    pub fn current() -> Option<Foreground> {
        // SAFETY: no arguments; null when no window is in the foreground.
        let hwnd = unsafe { GetForegroundWindow() };
        if hwnd.is_null() {
            return None;
        }
        let host_pid = pid_of(hwnd);
        let app = describe(host_pid)?;
        if !app.exe.eq_ignore_ascii_case(UWP_HOST) {
            return Some(app);
        }
        let mut search = ChildSearch { host_pid, found: 0 };
        // SAFETY: the callback only touches `search`, which outlives the call.
        unsafe {
            EnumChildWindows(
                hwnd,
                Some(find_foreign_child),
                &mut search as *mut ChildSearch as LPARAM,
            )
        };
        describe(search.found).or(Some(app))
    }

    /// Seconds since the last keyboard/mouse input (controllers don't count).
    pub fn idle_seconds() -> Option<u64> {
        let mut info = LASTINPUTINFO {
            cbSize: size_of::<LASTINPUTINFO>() as u32,
            dwTime: 0,
        };
        // SAFETY: info is a valid, sized LASTINPUTINFO.
        unsafe {
            if GetLastInputInfo(&mut info) == 0 {
                return None;
            }
            Some(u64::from(GetTickCount().wrapping_sub(info.dwTime)) / 1000)
        }
    }

    /// "FileDescription" from the exe's version resource ("Google Chrome", "Discord").
    pub fn app_description(path: &str) -> Option<String> {
        let path_w = wide(path);
        // SAFETY: buffers are sized from the API's own answers; pointers returned by
        // VerQueryValueW point into `data`, which stays alive while they are read.
        unsafe {
            let size = GetFileVersionInfoSizeW(path_w.as_ptr(), null_mut());
            if size == 0 {
                return None;
            }
            let mut data = vec![0u8; size as usize];
            if GetFileVersionInfoW(path_w.as_ptr(), 0, size, data.as_mut_ptr().cast()) == 0 {
                return None;
            }
            let block: *const c_void = data.as_ptr().cast();
            let mut translations = vec![(0x0409u16, 0x04b0u16), (0x0409, 0x04e4)];
            let mut ptr: *mut c_void = null_mut();
            let mut len = 0u32;
            let key = wide("\\VarFileInfo\\Translation");
            if VerQueryValueW(block, key.as_ptr(), &mut ptr, &mut len) != 0 && !ptr.is_null() {
                let pairs = len as usize / 4;
                let raw = std::slice::from_raw_parts(ptr as *const u16, pairs * 2);
                let found: Vec<(u16, u16)> = raw.chunks_exact(2).map(|p| (p[0], p[1])).collect();
                translations.splice(0..0, found);
            }
            for (lang, codepage) in translations {
                let key = wide(&format!(
                    "\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
                ));
                let mut ptr: *mut c_void = null_mut();
                let mut len = 0u32;
                if VerQueryValueW(block, key.as_ptr(), &mut ptr, &mut len) != 0
                    && !ptr.is_null()
                    && len > 0
                {
                    let text =
                        from_wide(std::slice::from_raw_parts(ptr as *const u16, len as usize));
                    let text = text.trim();
                    if !text.is_empty() {
                        return Some(text.to_owned());
                    }
                }
            }
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exe_stem_drops_the_extension_only() {
        assert_eq!(
            exe_stem("VALORANT-Win64-Shipping.exe"),
            "VALORANT-Win64-Shipping"
        );
        assert_eq!(exe_stem("Code.EXE"), "Code");
        assert_eq!(exe_stem("exe"), "exe");
        assert_eq!(exe_stem("python3"), "python3");
    }

    #[cfg(windows)]
    #[test]
    fn reads_something_on_windows() {
        // Not asserting a specific app: CI or a locked screen may have none.
        let _ = current();
        assert!(idle_seconds().is_some());
        let own = std::env::current_exe().unwrap();
        let _ = app_description(&own.to_string_lossy());
    }
}
