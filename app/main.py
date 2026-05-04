from .alerts import ensure_default_agent_alerts
from .data import load_companies
from .scheduler import AlertScheduler
from .ui.main_window import MainWindow


def main() -> None:
    try:
        ensure_default_agent_alerts([c.key for c in load_companies()])
    except Exception:
        pass
    scheduler = AlertScheduler()
    scheduler.start()
    try:
        app = MainWindow()
        app.mainloop()
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
