//! TermScope (Tauri V2) — wires the dictionary, matcher, knowledge store, tray,
//! global hotkeys and the floating-card window together. The Rust analogue of
//! `legacy/src/termscope/app.py::run`.

mod audio;
mod commands;
mod config;
mod dictionary;
mod history;
mod knowledge;
mod library;
mod matcher;
mod notifier;
mod paths;
mod selection;
mod startup;
mod state;
mod tray;

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

use crate::state::AppState;

#[cfg(desktop)]
fn handle_shortcut(
    app: &tauri::AppHandle,
    shortcut: &tauri_plugin_global_shortcut::Shortcut,
    event: tauri_plugin_global_shortcut::ShortcutEvent,
) {
    use tauri_plugin_global_shortcut::ShortcutState;
    if event.state() != ShortcutState::Pressed {
        return;
    }
    let cfg = app.state::<AppState>().config.lock().unwrap().clone();
    let parse = |s: &str| s.parse::<tauri_plugin_global_shortcut::Shortcut>().ok();
    if parse(&cfg.hotkey_explain_selection).as_ref() == Some(shortcut) {
        commands::run_explain_selection(app.clone());
    } else if parse(&cfg.hotkey_mark_last_learned).as_ref() == Some(shortcut) {
        commands::run_mark_last_learned(app.clone());
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();

    #[cfg(desktop)]
    {
        builder = builder
            // Single-instance MUST be registered first: a 2nd launch focuses the hub.
            .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
                commands::show_main(app.clone());
            }))
            .plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(handle_shortcut)
                    .build(),
            );
    }

    builder
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let handle = app.handle().clone();
            app.manage(AppState::init(&handle));

            tray::build_tray(&handle)?;

            // The floating-card overlay: transparent, frameless, always-on-top,
            // off the taskbar, never steals focus. It sizes/positions itself.
            WebviewWindowBuilder::new(app, "cards", WebviewUrl::App("cards.html".into()))
                .title("TermScope Notifications")
                .inner_size(420.0, 720.0)
                .decorations(false)
                .transparent(true)
                .always_on_top(true)
                .skip_taskbar(true)
                .resizable(false)
                .shadow(false)
                .focused(false)
                .visible(false)
                .build()?;

            // Register the configured global hotkeys.
            #[cfg(desktop)]
            {
                use tauri_plugin_global_shortcut::GlobalShortcutExt;
                let cfg = handle.state::<AppState>().config.lock().unwrap().clone();
                let gs = handle.global_shortcut();
                for combo in [&cfg.hotkey_explain_selection, &cfg.hotkey_mark_last_learned] {
                    if let Ok(sc) = combo.parse::<tauri_plugin_global_shortcut::Shortcut>() {
                        let _ = gs.register(sc);
                    }
                }
            }

            // Auto-start listening if the user opted in (bind first to avoid
            // holding the config lock while audio.start re-locks it).
            let on_startup = handle.state::<AppState>().config.lock().unwrap().listen_on_startup;
            if on_startup {
                let _ = handle.state::<AppState>().audio.start(&handle);
            }

            // X closes to tray only if the user opted in; otherwise it quits.
            if let Some(main) = app.get_webview_window("main") {
                let h = handle.clone();
                main.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        let to_tray = h.state::<AppState>().config.lock().unwrap().close_to_tray;
                        if to_tray {
                            api.prevent_close();
                            if let Some(w) = h.get_webview_window("main") {
                                let _ = w.hide();
                            }
                        } else {
                            h.exit(0);
                        }
                    }
                });
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_entries,
            commands::get_knowledge,
            commands::get_history,
            commands::get_filler_words,
            commands::clear_history,
            commands::get_library_detail,
            commands::get_config,
            commands::set_config_key,
            commands::begin_card_placement,
            commands::save_card_placement,
            commands::mark_learned,
            commands::unlearn,
            commands::reset_progress,
            commands::export_progress,
            commands::explain_selection,
            commands::mark_last_learned,
            commands::open_url,
            commands::focus_library_term,
            commands::show_main,
            commands::quit_app,
            commands::startup_enabled,
            commands::set_startup,
            commands::is_listening,
            commands::audio_status,
            commands::toggle_listening,
        ])
        .build(tauri::generate_context!())
        .expect("error while building TermScope")
        .run(|handle, event| {
            // Kill the audio sidecar when the app exits (no orphaned python).
            if let tauri::RunEvent::Exit = event {
                handle.state::<AppState>().audio.stop();
            }
        });
}
