import re, datetime, pytz, aiofiles, os, json, asyncio
import httpx
from pyrogram import filters
from pyrogram.types import Message
from Extractor import app
from config import PREMIUM_LOGS
from Extractor.core.utils import forward_to_log

async def sanitize_bname(bname, max_length=50):
    bname = re.sub(r'[\\/:*?"<>|\t\n\r]+', '', bname).strip()
    return bname[:max_length]

async def fetch_post(url, json=None, headers=None):
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(url, json=json, headers=headers)
        return res.json()

async def fetch_get(url, headers=None):
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(url, headers=headers)
        return res.json()

async def fetch_course_details(batch_id, headers):
    # Try v1 first
    url_v1 = f"https://backend.studyiq.net/app-content-ws/v1/course/getDetails?courseId={batch_id}"
    data = await fetch_get(url_v1, headers)
    if data.get("data"):
        return data, "v1"

    # If v1 fails, try v2
    url_v2 = f"https://backend.studyiq.net/app-content-ws/v2/course/getDetails?courseId={batch_id}"
    data = await fetch_get(url_v2, headers)
    if data.get("data"):
        return data, "v2"

    return {}, None

async def fetch_module_details(batch_id, parent_id, version, headers):
    url = f"https://backend.studyiq.net/app-content-ws/{version}/course/getDetails?courseId={batch_id}&parentId={parent_id}"
    return await fetch_get(url, headers)

async def fetch_lesson_details(batch_id, topic_id, sub_id, version, headers):
    url = f"https://backend.studyiq.net/app-content-ws/{version}/course/getDetails?courseId={batch_id}&parentId={topic_id}/{sub_id}"
    return await fetch_get(url, headers)

async def fetch_lesson_data(lid, batch_id, headers):
    # Try v1 first
    url_v1 = f"https://backend.studyiq.net/app-content-ws/api/lesson/data?lesson_id={lid}&courseId={batch_id}"
    data = await fetch_get(url_v1, headers)
    if data.get("options"):
        return data

    # Try v2
    url_v2 = f"https://backend.studyiq.net/app-content-ws/v2/lesson/data?lesson_id={lid}&courseId={batch_id}"
    data = await fetch_get(url_v2, headers)
    return data

async def save_and_send_file(app, m, all_urls, start_time, bname, batch_id):
    bname = await sanitize_bname(bname)
    txt_path = f"{bname}.txt"
    json_path = f"{bname}.json"
    local_time = datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
    minutes, seconds = divmod((datetime.datetime.now() - start_time).total_seconds(), 60)

    all_text = "\n".join(all_urls)
    
    # Enhanced content counting with icons
    video_count = sum(1 for line in all_urls if "🎬" in line)
    pdf_count = sum(1 for line in all_urls if "📄" in line)
    doc_count = sum(1 for line in all_urls if "📑" in line)
    image_count = sum(1 for line in all_urls if "🖼" in line)
    folder_count = sum(1 for line in all_urls if "📁" in line and "====" in line)
    note_count = sum(1 for line in all_urls if "📝" in line)
    total_links = len(all_urls)
    other_count = total_links - (video_count + pdf_count + doc_count + image_count + folder_count + note_count)

    caption = (
        f"🎓 COURSE EXTRACTED 🎓\n\n"
        f"📚 BATCH: {bname} (ID: {batch_id})\n"
        f"⏱ TIME: {int(minutes):02d}:{int(seconds):02d}\n"
        f"📅 DATE: {local_time.strftime('%d-%m-%Y %H:%M:%S')} IST\n\n"
        f"📊 STATS\n"
        f"├─ 📁 Total Links: {total_links}\n"
        f"├─ 🎬 Videos: {video_count}\n"
        f"├─ 📄 PDFs: {pdf_count}\n"
        f"├─ 📑 Docs: {doc_count}\n"
        f"├─ 🖼 Images: {image_count}\n"
        f"├─ 📝 Notes: {note_count}\n"
        f"└─ 📦 Others: {other_count}\n\n"
        f"🚀 By: @{(await app.get_me()).username}\n"
        f"╾───• :𝐈𝐓'𝐬𝐆𝐎𝐋𝐔.™®: •───╼"
    )

    async with aiofiles.open(txt_path, 'w', encoding='utf-8') as f:
        await f.writelines([url + '\n' for url in all_urls])

    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(all_urls, jf, indent=2, ensure_ascii=False)

    await m.reply_document(txt_path, caption=caption)
    await m.reply_document(json_path, caption=f"📦 JSON for: {bname}")
    await app.send_document(PREMIUM_LOGS, txt_path, caption=caption)
    await app.send_document(PREMIUM_LOGS, json_path, caption=f"📦 JSON for: {bname}")
    os.remove(txt_path)
    os.remove(json_path)

@app.on_message(filters.command(["iq"]))
async def handle_iq_logic(app, m: Message):
    try:
        prompt = await m.reply_text(
            "🔹 STUDY IQ EXTRACTOR 🔹\n\n"
            "📌 You can send:\n"
            "1. Phone Number (📱) for OTP\n"
            "2. OR Direct API Token (🔑)\n\n"
            "📤 Send Phone or Token:"
        )
        input1 = await app.listen(m.chat.id)
        await forward_to_log(input1, "StudyIQ Extractor")
        await input1.delete()
        raw = input1.text.strip()

        if raw.startswith("eyJ"):
            token = raw
        else:
            otp_res = await fetch_post("https://www.studyiq.net/api/web/userlogin", json={"mobile": raw})
            user_id = otp_res.get('data', {}).get('user_id')
            if not user_id:
                return await prompt.edit("❌ Failed to send OTP. Try again.")

            await prompt.edit("📬 OTP sent. Reply with the OTP.")
            otp_input = await app.listen(m.chat.id)
            otp = otp_input.text.strip()
            await otp_input.delete()

            login_res = await fetch_post("https://www.studyiq.net/api/web/web_user_login", json={"user_id": user_id, "otp": otp})
            token = login_res.get('data', {}).get('api_token')
            if not token:
                return await prompt.edit("❌ Invalid OTP or login error.")
            await m.reply_text(f"🔑 Token:\n`{token}`")
            await asyncio.sleep(1)

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "okhttp/4.9.1",
            "platform": "android",
        }

        courses = await fetch_get("https://backend.studyiq.net/app-content-ws/api/v1/getAllPurchasedCourses?source=APP", headers)
        course_list = courses.get("data", [])
        if not course_list:
            return await prompt.edit("❌ No courses found or token invalid.")

        batch_text, ids = "", []
        for course in course_list:
            cid, name = course.get("courseId"), course.get("courseTitle", "Untitled")
            batch_text += f"{cid} - {name}\n"
            ids.append(str(cid))

        await prompt.edit(
            f"✅ Login Successful\n\n"
            f"📚 Batches:\n\n{batch_text}\n"
            f"👉 Send Batch ID to extract (e.g. {ids[0]}&{ids[1]})"
        )

        input2 = await app.listen(m.chat.id)
        await prompt.delete(), input2.delete()
        batch_ids = input2.text.strip().split("&")

        for batch_id in batch_ids:
            start_time = datetime.datetime.now()
            status = await m.reply_text(f"⏳ Extracting: {batch_id}")
            course, version = await fetch_course_details(batch_id, headers)
            if not course or not course.get("data"):
                await m.reply(f"⚠️ Skipped: {batch_id} — No modules found (v1/v2).")
                await status.delete()
                continue

            bname = course.get("courseTitle", f"Batch_{batch_id}")
            modules = course.get("data", [])
            all_urls = []

            for mod in modules:
                topic_id = mod.get("contentId")
                topic_name = mod.get("name")
                
                if topic_name:
                    all_urls.append(f"\n📁 {topic_name}\n{'=' * (len(topic_name) + 4)}\n")
                
                subdata = await fetch_module_details(batch_id, topic_id, version, headers)

                for sub in subdata.get("data", []):
                    sub_id, sub_name = sub.get("contentId"), sub.get("name")
                    if sub_name:
                        all_urls.append(f"\n  📁 {sub_name}\n  {'=' * (len(sub_name) + 4)}\n")
                    
                    lessons = await fetch_lesson_details(batch_id, topic_id, sub_id, version, headers)

                    for lesson in lessons.get("data", []):
                        name, url = lesson.get("name", "Untitled"), lesson.get("videoUrl")
                        if url:
                            video_extensions = ('.m3u8', '.mpd', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm')
                            is_video = (
                                url.lower().endswith(video_extensions) or 
                                "playlist.m3u8" in url or 
                                "master.m3u8" in url or
                                "studyiq.net/video" in url
                            )
                            if is_video:
                                icon = "🎬"
                            elif url.lower().endswith('.pdf'):
                                icon = "📄"
                            elif url.lower().endswith(('.doc', '.docx', '.ppt', '.pptx')):
                                icon = "📑"
                            elif url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                                icon = "🖼"
                            else:
                                icon = "📄"
                            all_urls.append(f"    {icon} {name}: {url}")

                        lid = lesson.get("contentId")
                        details = await fetch_lesson_data(lid, batch_id, headers)

                        for o in details.get("options", []):
                            for f in o.get("urls", []):
                                fname, furl = f.get("name", "Note"), f.get("url")
                                if furl:
                                    all_urls.append(f"    📝 {fname}: {furl}")

            await status.delete()
            if all_urls:
                await save_and_send_file(app, m, all_urls, start_time, bname, batch_id)
            else:
                await m.reply("⚠️ No content found in this batch.")

        await m.reply("✅ DONE")
    except Exception as e:
        await m.reply(f"❌ Error:\n{e}")
