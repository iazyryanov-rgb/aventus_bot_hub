from .alerts import (
    ensure_default_agent_alerts,
    ensure_default_ai_audit_alerts,
    ensure_default_health_alerts,
)
from .audit_queue import get_queue, reconcile_orphans
from .data import load_companies
from .hub_changelog import maybe_send_hub_changelog
from .paths import icon_path
from .scheduler import AlertScheduler
from .ui.main_window import MainWindow
from .ui.tray import TrayController


def main() -> None:
    try:
        keys = [c.key for c in load_companies()]
        ensure_default_agent_alerts(keys)
        ensure_default_ai_audit_alerts(keys)
        ensure_default_health_alerts(keys)
    except Exception:
        pass
    # Mark any audit jobs that were running when the previous process
    # died as `interrupted` — the panel will surface them so the
    # operator can re-run.
    try:
        reconcile_orphans()
    except Exception:
        pass
    # If the build's SHA differs from the last one we shipped a
    # changelog for, post the diff to the general topic. First run
    # records baseline silently. Best-effort — never blocks startup.
    try:
        maybe_send_hub_changelog()
    except Exception:
        pass
    scheduler = AlertScheduler()
    scheduler.start()
    audit_queue = get_queue()
    tray = TrayController()
    try:
        app = MainWindow()
        # Install the X = hide-to-tray hook. If pystray isn't available
        # (or icon file missing), tray.attach returns False and the
        # window keeps its default close behavior.
        tray.attach(
            app,
            icon_png_path=icon_path(),
            on_quit=app.destroy,
        )
        app.mainloop()
    finally:
        tray.shutdown()
        scheduler.stop()
        audit_queue.shutdown()


if __name__ == "__main__":
    main()
