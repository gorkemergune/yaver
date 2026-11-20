//! Tray icon: the windows skip the taskbar, so this is where "quit" and the
//! autostart switch live (the settings view has the same switch).

use crate::{autostart, windows};
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, Wry};

/// Tray menu labels (user-facing, Turkish; the web app keeps its own in `web/src/i18n`).
mod tr {
    pub const TOOLTIP: &str = "Yaver";
    pub const OPEN_CHAT: &str = "Sohbeti aç";
    pub const SHOW_LOGO: &str = "Logoyu göster";
    pub const AUTOSTART: &str = "Oturum açılışında başlat";
    pub const QUIT: &str = "Çıkış";
}

const OPEN_CHAT: &str = "open_chat";
const SHOW_LOGO: &str = "show_logo";
const AUTOSTART: &str = "autostart";
const QUIT: &str = "quit";

/// Kept in app state so the settings view can update the check mark.
pub struct TrayItems {
    pub autostart: CheckMenuItem<Wry>,
}

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    let enabled = autostart::is_enabled(app);
    let autostart_item =
        CheckMenuItem::with_id(app, AUTOSTART, tr::AUTOSTART, true, enabled, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &MenuItem::with_id(app, OPEN_CHAT, tr::OPEN_CHAT, true, None::<&str>)?,
            &MenuItem::with_id(app, SHOW_LOGO, tr::SHOW_LOGO, true, None::<&str>)?,
            &PredefinedMenuItem::separator(app)?,
            &autostart_item,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, QUIT, tr::QUIT, true, None::<&str>)?,
        ],
    )?;
    app.manage(TrayItems {
        autostart: autostart_item,
    });

    let mut builder = TrayIconBuilder::with_id("main")
        .tooltip(tr::TOOLTIP)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            OPEN_CHAT => log_err(windows::show_chat(app)),
            SHOW_LOGO => log_err(windows::reveal_bubble(app)),
            AUTOSTART => {
                let wanted = !autostart::is_enabled(app);
                if let Err(err) = autostart::set(app, wanted) {
                    log::warn!("autostart: {err}");
                }
                sync(app);
            }
            QUIT => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                log_err(windows::toggle_chat(tray.app_handle()));
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

/// Puts the tray check mark in line with the real (registry) state.
pub fn sync(app: &AppHandle) {
    if let Some(items) = app.try_state::<TrayItems>() {
        let _ = items.autostart.set_checked(autostart::is_enabled(app));
    }
}

fn log_err(result: tauri::Result<()>) {
    if let Err(err) = result {
        log::warn!("tray: {err}");
    }
}
