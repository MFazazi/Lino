use std::{collections::HashSet, io::{Read, Write, BufRead, BufReader}, process::{Command, Stdio}, sync::{Arc, Mutex}, time::{Duration, Instant}};
use serde_json::{json, Value};
use tauri::{State, WebviewWindow};
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[tauri::command]
pub fn play_notification_sound(window: WebviewWindow) -> Result<(), String> {
    local_island(&window)?;
    #[cfg(target_os = "windows")]
    {
        #[link(name = "user32")]
        extern "system" { fn MessageBeep(kind: u32) -> i32; }
        if unsafe { MessageBeep(0x40) } == 0 { return Err("Son Windows indisponible.".into()); }
    }
    Ok(())
}

#[derive(Default)]
pub struct RelayState {
    worker: Mutex<Option<ScanWorker>>,
    pending: Mutex<HashSet<String>>,
    sent: Mutex<HashSet<String>>,
}


struct ScanWorker {
    child: std::process::Child,
    latest: Arc<Mutex<(Instant, Value)>>,
}

impl Drop for ScanWorker {
    fn drop(&mut self) { let _ = self.child.kill(); let _ = self.child.wait(); }
}

impl ScanWorker {
    fn start() -> Result<Self, String> {
        let core = super::find_core_dir().ok_or("Dossier Lino introuvable.")?;
        let script = core.parent().ok_or("Dossier Lino introuvable.")?.join("integrations/desktop/approval_bridge.py");
        let mut command = Command::new(core.join(".venv/Scripts/python.exe"));
        command.arg(script).arg("--watch").current_dir(core).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
        #[cfg(target_os = "windows")]
        command.creation_flags(0x08000000);
        let mut child = command.spawn().map_err(|e| e.to_string())?;
        let stdout = child.stdout.take().ok_or("Relais indisponible.")?;
        let latest = Arc::new(Mutex::new((Instant::now(), json!({"ok":true,"approvals":[]}))));
        let output = latest.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break; };
                if let Ok(value) = serde_json::from_str::<Value>(&line) {
                    if let Ok(mut data) = output.lock() { *data = (Instant::now(), value); }
                }
            }
        });
        Ok(Self {child, latest})
    }
}

fn local_island(window: &WebviewWindow) -> Result<(), String> {
    let url = window.url().map_err(|e| e.to_string())?;
    let local = url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost")
        || (cfg!(debug_assertions) && url.host_str() == Some("localhost") && url.port() == Some(1420));
    if window.label() != "island" || !local { return Err("Réponse réservée à l’island Lino locale.".into()); }
    Ok(())
}

fn bridge(input: Value) -> Result<Value, String> {
    let core = super::find_core_dir().ok_or("Dossier Lino introuvable.")?;
    let script = core.parent().ok_or("Dossier Lino introuvable.")?.join("integrations/desktop/approval_bridge.py");
    let mut command = Command::new(core.join(".venv/Scripts/python.exe"));
    command.arg(script).current_dir(core).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(target_os = "windows")]
    command.creation_flags(0x08000000);
    let mut child = command.spawn().map_err(|e| e.to_string())?;
    let mut stdin = child.stdin.take().ok_or("Relais indisponible.")?;
    stdin.write_all(input.to_string().as_bytes()).map_err(|e| e.to_string())?;
    drop(stdin);
    let stdout = child.stdout.take().ok_or("Relais indisponible.")?;
    let reader = std::thread::spawn(move || {
        let mut output = String::new();
        stdout.take(512 * 1024).read_to_string(&mut output).map(|_| output)
    });
    let deadline = Instant::now() + Duration::from_secs(8);
    while child.try_wait().map_err(|e| e.to_string())?.is_none() {
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            let _ = reader.join();
            return Err("Le relais ne répond pas. Vérifie la demande dans l’application avant de réessayer.".into());
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let output = reader.join().map_err(|_| "Lecture du relais impossible.")?.map_err(|e| e.to_string())?;
    let value: Value = serde_json::from_str(output.trim()).map_err(|_| "Réponse du relais illisible.")?;
    if value["ok"] != true { return Err(value["message"].as_str().unwrap_or("Relais indisponible.").to_string()); }
    Ok(value)
}

#[tauri::command]
pub async fn scan_desktop_approvals(window: WebviewWindow, state: State<'_, RelayState>) -> Result<Value, String> {
    local_island(&window)?;
    let mut result = {
        let mut worker = state.worker.lock().map_err(|_| "Relais occupé.")?;
        let restart = match worker.as_mut() {
            None => true,
            Some(w) => w.child.try_wait().map_err(|e| e.to_string())?.is_some()
                || w.latest.lock().map_err(|_| "Relais occupé.")?.0.elapsed() > Duration::from_secs(10),
        };
        if restart { *worker = Some(ScanWorker::start()?); }
        let latest = worker.as_ref().ok_or("Relais indisponible.")?.latest.lock().map_err(|_| "Relais occupé.")?;
        latest.1.clone()
    };
    if result["ok"] != true { return Err(result["message"].as_str().unwrap_or("Relais indisponible.").to_string()); }
    let sent = state.sent.lock().map_err(|_| "Relais occupé.")?;
    if let Some(items) = result["approvals"].as_array_mut() {
        items.retain(|item| !sent.contains(item["id"].as_str().unwrap_or("")));
        *state.pending.lock().map_err(|_| "Relais occupé.")? = items.iter().filter_map(|i| i["id"].as_str().map(String::from)).collect();
    }
    Ok(result)
}

#[tauri::command]
pub async fn answer_desktop_approval(window: WebviewWindow, state: State<'_, RelayState>, id: String, decision: String) -> Result<Value, String> {
    local_island(&window)?;
    if decision != "allow" && decision != "deny" { return Err("Choix invalide.".into()); }
    {
        let mut sent = state.sent.lock().map_err(|_| "Relais occupé.")?;
        if sent.contains(&id) || !state.pending.lock().map_err(|_| "Relais occupé.")?.remove(&id) {
            return Err("Demande expirée ou choix déjà transmis.".into());
        }
        // Consume once even on timeout: an uncertain action must never be repeated.
        sent.insert(id.clone());
    }
    tauri::async_runtime::spawn_blocking(move || bridge(json!({"action":"respond","id":id,"decision":decision})))
        .await.map_err(|e| e.to_string())?
}
