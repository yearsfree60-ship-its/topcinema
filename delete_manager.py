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

  scrub-run-manifests <OUTPUT_DIR>
    [إضافة — يشمل الحذف الآن سجلات التشغيلات (output/runs/run-<id>.json)
    وأي أثر مشابه لها متعلق بفصول لم يعد لها وجود، لا manifest.json
    الرئيسي فقط] compress_chapters.py يكتب لكل تشغيلة ضغط ناجحة ملف سجلّ
    مستقل بنفس بنية manifest.json تمامًا (راجع build_run_manifest/
    merge_manifest_dict هناك: {"manga": {manga_id: {..., "chapters": [...]}}}
    — لا فرق بنيويًا عن manifest.json إطلاقًا).

    [تصحيح — مقارنة فعلية بالقرص، لا اعتمادًا على DELETE_PAYLOAD هذه
    التشغيلة تحديدًا] بدل الاعتماد فقط على قائمة الحذف الحالية (التي لا
    تغطّي إلا ما يُطلَب حذفه الآن)، هذا الأمر يقارن كل فصل مذكور بأي سجلّ
    runs/run-*.json مع وجوده الفعلي الحالي على القرص
    (OUTPUT_DIR/<manga_id>/ch-<num>) — أي فصل غير موجود فعليًا (سواء
    حُذف بهذه التشغيلة بالضبط عبر compute-targets/git rm أعلاه، أو حُذف
    سابقًا بأي طريقة أخرى وبقي سجلّه يتيمًا من قبل إضافة هذه الميزة
    نفسها) يُزال من السجلّ. هذا يجعله فحصًا عامًا شاملًا (لا مقيَّدًا
    بـDELETE_PAYLOAD)، ويُستدعى من apply_and_stage بعد حلقة git rm
    الخاصة بمجلدات targets.txt مباشرة (فالقرص عندها يعكس فعليًا الفصول
    المتبقية بعد حذف هذه التشغيلة) — على كل محاولة دفع، لا مرة واحدة
    فقط، بنفس ضمان manifest.json تمامًا.

    لو أصبح ملف السجلّ فارغًا كليًا (لا مانهوات متبقية به) يُحذَف من
    القرص فعليًا ويُطبَع بسطر "DELETE <مسار نسبي>"؛ لو تبقّى به محتوى
    جزئي (تشغيلة عالجت عدة فصول، بعضها فقط لم يعد موجودًا) يُعاد كتابته
    بالقرص بمحتواه المُصفَّى ويُطبَع بسطر "KEEP <مسار نسبي>" (يحتاج
    git add لاحقًا لا git rm). لا شيء يُطبَع لملف غير متأثر إطلاقًا (كل
    فصوله المذكورة لا تزال موجودة فعليًا — لا حاجة لمس القرص أو git به).
    المسارات المطبوعة نسبية لـOUTPUT_DIR (بادئة "runs/") لتُستخدَم
    مباشرة بـ"$git_rel_output/$path" بالـworkflow، بنفس نمط targets.txt.
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


def _apply_delete_to_manifest(manifest: dict, payload: dict) -> dict:
    """[يُستخدَم فقط لـmanifest.json الرئيسي عبر apply-manifest] يحذف من
    manifest (قاموس بصيغة {"manga": {...}}) كل ما يطابق DELETE_PAYLOAD:
    مانهوات كاملة بالكامل، أو فصولًا محدَّدة (وإسقاط المانهوا كليًا لو
    أصبحت بلا فصول متبقية). لا يُعدِّل manifest المُمرَّر بمكانه — يُرجع
    قاموسًا جديدًا."""
    full_manga_set = set(payload["full_manga"])
    manga = dict(manifest.get("manga", {}))

    for manga_id in full_manga_set:
        manga.pop(manga_id, None)

    for item in payload["chapters"]:
        manga_id, num = item["manga_id"], str(item["num"])
        if manga_id in full_manga_set:
            continue
        entry = manga.get(manga_id)
        if not entry:
            continue
        entry = dict(entry)
        entry["chapters"] = [c for c in entry.get("chapters", []) if str(c.get("num")) != num]
        if not entry["chapters"]:
            manga.pop(manga_id, None)
        else:
            manga[manga_id] = entry

    return {**manifest, "manga": manga}


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
    src = Path(in_path)
    manifest = json.loads(src.read_text(encoding="utf-8")) if src.is_file() else {}
    manifest = _apply_delete_to_manifest(manifest, payload)
    Path(out_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cmd_scrub_run_manifests(output_dir_arg: str) -> None:
    output_dir = Path(output_dir_arg)
    runs_dir = output_dir / "runs"
    if not runs_dir.is_dir():
        return

    def chapter_exists_on_disk(manga_id: str, num: str) -> bool:
        return (output_dir / manga_id / f"ch-{num}").is_dir()

    for run_file in sorted(runs_dir.glob("run-*.json")):
        try:
            original = json.loads(run_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️ تعذّر قراءة {run_file.name} كـJSON صالح — تُرِك بلا تغيير: {e}", file=sys.stderr)
            continue

        original_manga = original.get("manga", {})
        filtered_manga = {}
        for manga_id, entry in original_manga.items():
            kept_chapters = [
                c for c in entry.get("chapters", [])
                if chapter_exists_on_disk(manga_id, str(c.get("num")))
            ]
            if kept_chapters:
                filtered_manga[manga_id] = {**entry, "chapters": kept_chapters}

        rel_path = f"runs/{run_file.name}"
        if filtered_manga == original_manga:
            continue  # كل الفصول المذكورة لا تزال موجودة فعليًا — لا حاجة لمس شيء

        if not filtered_manga:
            run_file.unlink()
            print(f"DELETE {rel_path}")
        else:
            filtered = {**original, "manga": filtered_manga}
            run_file.write_text(
                json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"KEEP {rel_path}")


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "الاستخدام: delete_manager.py compute-targets | apply-manifest <in> <out> "
            "| scrub-run-manifests <output_dir>",
            file=sys.stderr,
        )
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "compute-targets":
        cmd_compute_targets()
    elif cmd == "apply-manifest":
        if len(sys.argv) != 4:
            print("الاستخدام: delete_manager.py apply-manifest <in> <out>", file=sys.stderr)
            sys.exit(1)
        cmd_apply_manifest(sys.argv[2], sys.argv[3])
    elif cmd == "scrub-run-manifests":
        if len(sys.argv) != 3:
            print("الاستخدام: delete_manager.py scrub-run-manifests <output_dir>", file=sys.stderr)
            sys.exit(1)
        cmd_scrub_run_manifests(sys.argv[2])
    else:
        print(f"أمر غير معروف: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
