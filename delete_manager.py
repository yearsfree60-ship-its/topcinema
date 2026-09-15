"""
delete_manager.py
==================
يُستدعى حصرًا من workflow "حذف فصول/مانهوات" (delete-chapters.yml). لا علاقة له
بـcompress_chapters.py، لكنه يتبع نفس مبدأ الأمان الجوهري المُطبَّق هناك: أي
عملية git add/rm تقتصر على قائمة مسارات صريحة محسوبة هنا، ولا تُستخدم أبدًا
عملية شاملة (لا "git rm -r output/" ولا "git add -A") قد تلمس ملفات
تشغيلات/فروع عمل أخرى.

DELETE_PAYLOAD (متغيّر بيئة، JSON):
{
  "full_manga": ["manga_id1", ...],
  "chapters": [{"manga_id": "x", "num": "12"}, ...]
}

أوامر فرعية:
  compute-targets
    يفحص القرص فعليًا (OUTPUT_DIR) ويطبع، سطرًا سطرًا، كل مسار نسبي لـ
    OUTPUT_DIR يجب حذفه فعليًا (مجلدات فصول + مجلدات ocr_experiment + ملفات
    glossary). يُستدعى مرة واحدة فقط في بداية التشغيلة — النتيجة ثابتة لبقية
    محاولات الدفع (حتى لو أُعيدت المحاولة بعد فشل push).

  apply-manifest <مسار_دخل> <مسار_خرج>
    يقرأ manifest.json (أي نسخة، محلية أو مسحوبة طازجة من origin عبر
    "git show") ويطبّق عليه نفس DELETE_PAYLOAD حذفًا (عملية أحادية الاتجاه
    وآمنة التكرار idempotent — تطبيقها أكثر من مرة على نفس المدخل لا يغيّر
    شيئًا إضافيًا)، ثم يكتب الناتج بمسار_خرج. يُستدعى في كل محاولة دفع
    (الأولى وأي إعادة محاولة بعد فشل push) على نسخة manifest.json الأحدث من
    origin وقتها تحديدًا — لا على نسخة قديمة مخزَّنة محليًا — كي لا يُدفَع فوق
    إضافات تشغيلة أخرى متزامنة أُضيفت بمانهوات/فصول مختلفة تمامًا.
"""
import json
import os
import sys
from pathlib import Path


def _load_payload() -> dict:
    raw = os.environ.get("DELETE_PAYLOAD", "")
    if not raw.strip():
        print("⚠️ DELETE_PAYLOAD فارغ", file=sys.stderr)
        return {"full_manga": [], "chapters": []}
    try:
        payload = json.loads(raw)
    except Exception as e:
        print(f"❌ DELETE_PAYLOAD ليس JSON صالحًا: {e}", file=sys.stderr)
        sys.exit(1)
    payload.setdefault("full_manga", [])
    payload.setdefault("chapters", [])
    return payload


def cmd_compute_targets() -> None:
    output_dir = Path(os.environ["OUTPUT_DIR"])
    payload = _load_payload()
    targets: list[str] = []

    for manga_id in payload["full_manga"]:
        # المانهوا كاملة: مجلد صورها + كل مجلدات ocr_experiment المطابقة لها
        # (تُكتشَف بمسح القرص فعليًا، لا بالاعتماد على manifest.json — يضمن
        # هذا تنظيف أي مجلد OCR يتيم لأي سبب لم يعد بmanifest.json) + glossary.
        manga_dir = output_dir / manga_id
        if manga_dir.is_dir():
            targets.append(manga_id)

        ocr_dir = output_dir / "ocr_experiment"
        prefix = f"{manga_id}__ch-"
        if ocr_dir.is_dir():
            for child in sorted(ocr_dir.iterdir()):
                if child.is_dir() and child.name.startswith(prefix):
                    targets.append(f"ocr_experiment/{child.name}")

        glossary_path = output_dir / "ocr_experiment" / "glossary" / f"{manga_id}.json"
        if glossary_path.is_file():
            targets.append(f"ocr_experiment/glossary/{manga_id}.json")

    full_manga_set = set(payload["full_manga"])
    for item in payload["chapters"]:
        manga_id, num = item["manga_id"], str(item["num"])
        if manga_id in full_manga_set:
            continue  # مُغطاة بالفعل بحذف المانهوا كاملة أعلاه
        targets.append(f"{manga_id}/ch-{num}")
        targets.append(f"ocr_experiment/{manga_id}__ch-{num}")

    # إزالة التكرار مع الحفاظ على الترتيب — لا ضرر من تكرار مسار بـgit rm/add
    # لكن الأنظف تفاديه، وأوضح بسجلّات الـworkflow.
    seen = set()
    for t in targets:
        if t not in seen:
            seen.add(t)
            print(t)


def cmd_apply_manifest(in_path: str, out_path: str) -> None:
    payload = _load_payload()
    full_manga_set = set(payload["full_manga"])

    src = Path(in_path)
    manifest = json.loads(src.read_text(encoding="utf-8")) if src.is_file() else {}
    manga = manifest.get("manga", {})

    for manga_id in full_manga_set:
        manga.pop(manga_id, None)

    for item in payload["chapters"]:
        manga_id, num = item["manga_id"], str(item["num"])
        if manga_id in full_manga_set:
            continue
        entry = manga.get(manga_id)
        if not entry:
            continue
        entry["chapters"] = [c for c in entry.get("chapters", []) if str(c.get("num")) != num]
        if not entry["chapters"]:
            manga.pop(manga_id, None)

    manifest["manga"] = manga
    Path(out_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("الاستخدام: delete_manager.py compute-targets | apply-manifest <in> <out>", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "compute-targets":
        cmd_compute_targets()
    elif cmd == "apply-manifest":
        if len(sys.argv) != 4:
            print("الاستخدام: delete_manager.py apply-manifest <in> <out>", file=sys.stderr)
            sys.exit(1)
        cmd_apply_manifest(sys.argv[2], sys.argv[3])
    else:
        print(f"أمر غير معروف: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
