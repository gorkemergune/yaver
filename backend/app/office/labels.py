"""What an employee is doing, in words for the office panel ("Takvime bakıyor")."""

TOOL_LABELS: dict[str, str] = {
    "resolve_date": "Tarihi hesaplıyor",
    "get_ad_report": "Reklam raporlarına bakıyor",
    "analyze_ads": "Reklam raporunu analiz ediyor",
    "get_day_plan": "Günün planına bakıyor",
    "get_week_plan": "Haftanın planına bakıyor",
    "add_recurring_block": "Haftalık programa ekliyor",
    "update_recurring_block": "Haftalık programı güncelliyor",
    "cancel_block_on": "Dersi / bloğu iptal ediyor",
    "move_block_on": "Bloğu taşıyor",
    "add_event": "Takvime etkinlik ekliyor",
    "update_event": "Etkinliği güncelliyor",
    "delete_event": "Etkinliği siliyor",
    "log_attendance": "Devamsızlığı kaydediyor",
    "get_attendance_summary": "Devamsızlığa bakıyor",
    "list_attendance": "Devamsızlık kayıtlarına bakıyor",
    "delete_attendance": "Devamsızlık kaydını düzeltiyor",
    "set_attendance_baseline": "Eski devamsızlığı yazıyor",
    "set_absence_limit": "Devamsızlık sınırını yazıyor",
    "set_week_label": "Haftaya ad veriyor",
    "add_task": "Görev ekliyor",
    "complete_task": "Görevi kapatıyor",
    "add_followup": "Takip açıyor",
    "update_followup": "Takibi güncelliyor",
    "remember": "Not ediyor",
    "forget": "Bilgiyi siliyor",
    "add_note": "Defterine yazıyor",
    "get_notes": "Deftere bakıyor",
    "search_materials": "Ders notlarında arıyor",
    "get_syllabus": "Syllabus'a bakıyor",
    "save_material": "Ders notunu dosyalıyor",
    "generate_study_sheet": "Çalışma kağıdı yazıyor",
    "get_screen_time": "Ekran süresine bakıyor",
    "apply_proposal": "Öneriyi uyguluyor",
    "propose_schedule": "Ders programını okuyor",
    "undo": "Geri alıyor",
}
READING = "İsteği okuyor"
MERGING = "Cevapları topluyor"


def tool_label(tool: str) -> str:
    return TOOL_LABELS.get(tool, "Araç kullanıyor")


def waiting_for(name: str) -> str:
    return f"{name} çalışıyor, bekliyor"


def preview(text: str, limit: int = 120) -> str:
    """One line of a request for the panel."""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
