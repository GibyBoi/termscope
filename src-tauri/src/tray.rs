//! System-tray icon + menu, ported from `legacy/src/termscope/tray.py` (pystray)
//! to Tauri's built-in tray. Open / Quit; left-click opens the hub.

use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle,
};

pub fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Open TermScope", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Quit TermScope", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &sep, &quit])?;

    let mut builder = TrayIconBuilder::with_id("termscope-tray")
        .tooltip("TermScope")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => crate::commands::show_main(app.clone()),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                crate::commands::show_main(tray.app_handle().clone());
            }
        });

    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}
