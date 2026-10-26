"""Register (or update) the Windows Task Scheduler jobs for tcg-tracker. Run it yourself, once:

    .venv\\Scripts\\python scripts\\register_tasks.py            create / update the tasks
    .venv\\Scripts\\python scripts\\register_tasks.py --remove   delete them

Tasks (folder "tcg-tracker" in Task Scheduler), run as the current user, only while logged on, no admin needed:
  crawl            07:15 and 19:15  scripts/scheduled.py crawl            (crawl, then back up the database)
  check-freshness  12:30            scripts/scheduled.py check-freshness  (alert if no good crawl in 26 h)
A time missed because the PC was off or asleep runs as soon as it's available again.
Each run is limited to 2 hours (a 401 Games crawl alone can take ~30 min).
"""
from __future__ import annotations

import getpass
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"  # no console window
FOLDER = "\\tcg-tracker\\"
TASKS = {
    "crawl": ("crawl", ["07:15", "19:15"], "Crawl all stores, then back up the database"),
    "check-freshness": ("check-freshness", ["12:30"], "Alert if no good crawl in the last 26 hours"),
}


def task_xml(job: str, times: list[str], description: str, user: str) -> str:
    triggers = "".join(
        f"<CalendarTrigger><StartBoundary>2026-01-01T{t}:00</StartBoundary><Enabled>true</Enabled>"
        f"<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>" for t in times)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>tcg-tracker: {escape(description)}</Description></RegistrationInfo>
  <Triggers>{triggers}</Triggers>
  <Principals><Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType>
    <RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>{escape(str(PYTHONW))}</Command>
    <Arguments>"{escape(str(ROOT / "scripts" / "scheduled.py"))}" {job}</Arguments>
    <WorkingDirectory>{escape(str(ROOT))}</WorkingDirectory>
  </Exec></Actions>
</Task>
"""


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        print("Windows only; on Linux/macOS use cron, e.g. '15 7,19 * * * .venv/bin/python scripts/scheduled.py crawl'")
        return 2
    if not PYTHONW.exists():
        print(f"{PYTHONW} not found: create the virtualenv first (see README)")
        return 2
    if "--remove" in argv:
        for name in TASKS:
            subprocess.run(["schtasks", "/Delete", "/TN", FOLDER + name, "/F"])
        return 0
    user = f"{getpass.getuser()}"
    for name, (job, times, description) in TASKS.items():
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
            f.write(task_xml(job, times, description, user))
        try:
            r = subprocess.run(["schtasks", "/Create", "/TN", FOLDER + name, "/XML", f.name, "/F"])
        finally:
            Path(f.name).unlink()
        if r.returncode != 0:
            return r.returncode
    subprocess.run(["schtasks", "/Query", "/TN", FOLDER, "/FO", "TABLE"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
