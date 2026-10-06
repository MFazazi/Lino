mod approval_relay;
use approval_relay::{RelayState, scan_desktop_approvals, answer_desktop_approval, play_notification_sound};

use std::{
    fs::{create_dir_all, OpenOptions},
    io::Write,
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Command, Stdio},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{LogicalSize, Manager, PhysicalPosition, WebviewWindow};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

fn desktop_log(message: &str) {
    let Some(base) = std::env::var_os("LOCALAPPDATA") else { return; };
    let directory = PathBuf::from(base).join("Lino");
    if create_dir_all(&directory).is_err() { return; }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(directory.join("lino-desktop.log")) {
        let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs();
        let _ = writeln!(file, "{timestamp} {message}");
    }
}

fn core_is_running() -> bool {
    let address: SocketAddr = "127.0.0.1:8765".parse().expect("valid Lino Core address");
    TcpStream::connect_timeout(&address, Duration::from_millis(180)).is_ok()
}

fn project_root_candidates() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        roots.push(cwd.clone());
        if let Some(parent) = cwd.parent() { roots.push(parent.to_path_buf()); }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            // Also find the project from target/debug or target/release when launched by Explorer.
            roots.extend(dir.ancestors().take(4).map(PathBuf::from));
        }
    }
    roots
}

fn find_core_dir() -> Option<PathBuf> {
    project_root_candidates()
        .into_iter()
        .map(|root| root.join("core"))
        .find(|path| path.join("main.py").exists())
}

fn start_core_if_needed() {
    if core_is_running() { desktop_log("core: already running on 8765"); return; }
    let Some(core_dir) = find_core_dir() else { desktop_log("core: directory not found"); return; };
    let venv_python = core_dir.join(".venv").join("Scripts").join("python.exe");
    let (program, hidden) = if venv_python.exists() { (venv_python, true) } else { (PathBuf::from("python"), false) };
    let mut command = Command::new(program);
    command
        .arg(core_dir.join("main.py"))
        .current_dir(&core_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(target_os = "windows")]
    if hidden {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    match command.spawn() {
        Ok(child) => desktop_log(&format!("core: launched pid={}", child.id())),
        Err(error) => desktop_log(&format!("core: launch failed: {error}")),
    }
}

fn place_top_center(window: &WebviewWindow) -> Result<(), String> {
    let monitor = window.current_monitor().map_err(|e| e.to_string())?;
    let Some(monitor) = monitor else { return Ok(()); };
    let monitor_size = monitor.size();
    let monitor_position = monitor.position();
    let window_size = window.outer_size().map_err(|e| e.to_string())?;
    let x = monitor_position.x + ((monitor_size.width as i32 - window_size.width as i32) / 2);
    // Both notch sizes meet the physical top edge, including on scaled displays.
    let y = monitor_position.y;
    window.set_position(PhysicalPosition::new(x, y)).map_err(|e| e.to_string())?;
    Ok(())
}

fn size_for_mode(mode: &str) -> LogicalSize<f64> {
    match mode {
        "home" | "expanded" => LogicalSize::new(940.0, 480.0),
        _ => LogicalSize::new(360.0, 46.0),
    }
}

#[tauri::command]
async fn set_island_mode(app: tauri::AppHandle, mode: String) -> Result<(), String> {
    let result = (|| {
        let window = app.get_webview_window("island").ok_or("Fenêtre Lino introuvable")?;
        let mut size = size_for_mode(&mode);
        if let Some(monitor) = window.current_monitor().map_err(|e| e.to_string())? {
            let scale = monitor.scale_factor();
            size.width = size.width.min(monitor.size().width as f64 / scale);
            size.height = size.height.min(monitor.size().height as f64 / scale);
        }
        window.set_size(size).map_err(|e| e.to_string())?;
        place_top_center(&window)?;
        window.show().map_err(|e| e.to_string())?;
        if mode != "petit" { window.set_focus().map_err(|e| e.to_string())?; }
        desktop_log(&format!("window: mode={mode} visible={} position={:?} size={:?}",
            window.is_visible().unwrap_or(false), window.outer_position(), window.outer_size()));
        Ok(())
    })();
    if let Err(ref error) = result { desktop_log(&format!("window: resize failed: {error}")); }
    result
}

#[tauri::command]
async fn show_island(app: tauri::AppHandle) -> Result<(), String> {
    let window = app.get_webview_window("island").ok_or("Fenêtre Lino introuvable")?;
    place_top_center(&window)?;
    window.show().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
async fn hide_island(app: tauri::AppHandle) -> Result<(), String> {
    // Legacy Core versions use hide_all for sleep. Keep the island reachable.
    set_island_mode(app, "petit".into()).await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(RelayState::default())
        .setup(|app| {
            desktop_log("desktop: starting existing Lino island");
            let window = app.get_webview_window("island").ok_or("Lino island is missing")?;
            window.set_size(size_for_mode("petit"))?;
            place_top_center(&window).map_err(std::io::Error::other)?;
            window.show()?;
            desktop_log(&format!("window: startup visible={} position={:?} size={:?}",
                window.is_visible()?, window.outer_position(), window.outer_size()));
            std::thread::spawn(start_core_if_needed);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![set_island_mode, show_island, hide_island, scan_desktop_approvals, answer_desktop_approval, play_notification_sound])
        .run(tauri::generate_context!())
        .expect("error while running Lino");
}
