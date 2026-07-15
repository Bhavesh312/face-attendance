import streamlit as st  # UI
from db_utils import (
    create_class, get_classes_for_teacher, get_students_by_class,
    create_attendance_session, save_attendance_record, get_sessions_for_class,
    get_records_for_session, create_teacher, authenticate_teacher,
    delete_student, update_attendance_status, delete_class,
    get_all_teachers, get_attendance_history_for_student, add_student
)
import json, time, os, io
import numpy as np
import face_recognition
from PIL import Image, ImageDraw

st.set_page_config(page_title="Face Attendance", layout="wide")

st.markdown("""
<style>
    .main .block-container {padding-top: 2rem;}
    h1, h2, h3 {color: #1f2937;}
    div[data-testid="stExpander"] {border: 1px solid #e5e7eb; border-radius: 10px;}
    .stButton button {border-radius: 8px;}
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def warm_up_face_model():
    dummy_img = np.zeros((100, 100, 3), dtype='uint8')
    face_recognition.face_locations(dummy_img)
    return True

warm_up_face_model()

# ---------------- Shared registration logic ----------------
def run_registration_flow(class_id, key_prefix):
    photos_key = f"{key_prefix}_reg_photos"
    if photos_key not in st.session_state:
        st.session_state[photos_key] = []

    student_name = st.text_input("Your full name", key=f"{key_prefix}_student_name")

    cam_col, list_col = st.columns([1, 1])

    with cam_col:
        captured_photo = st.camera_input(
            "Open camera and capture a photo",
            key=f"{key_prefix}_camera_{len(st.session_state[photos_key])}"
        )
        if captured_photo is not None:
            if st.button("➕ Add this photo", key=f"{key_prefix}_add_photo"):
                st.session_state[photos_key].append(captured_photo.getvalue())
                st.rerun()

    with list_col:
        st.write(f"**Captured photos: {len(st.session_state[photos_key])}**")
        if st.session_state[photos_key]:
            thumb_cols = st.columns(min(5, len(st.session_state[photos_key])))
            for idx, photo_bytes in enumerate(st.session_state[photos_key]):
                thumb_cols[idx % len(thumb_cols)].image(photo_bytes, width=90)
        if st.button("🗑️ Clear captured photos", key=f"{key_prefix}_clear_photos"):
            st.session_state[photos_key] = []
            st.rerun()

    if st.button("✅ Register", type="primary", key=f"{key_prefix}_register_btn"):
        if not student_name.strip():
            st.error("Please enter your name.")
        elif not st.session_state[photos_key]:
            st.error("Please capture at least one photo (3-5 recommended) before registering.")
        else:
            class_folder = os.path.join("data", f"class_{class_id}")
            photos_folder = os.path.join(class_folder, "students_photos")
            os.makedirs(photos_folder, exist_ok=True)
            safe_name = "".join(c for c in student_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")

            collected_encodings = []
            first_photo_path = None
            skipped = 0

            for idx, photo_bytes in enumerate(st.session_state[photos_key]):
                img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
                img_np = np.array(img)

                face_locations = face_recognition.face_locations(img_np)
                if len(face_locations) != 1:
                    skipped += 1
                    st.warning(f"Photo {idx+1}: skipped ({'no face' if len(face_locations)==0 else 'multiple faces'} detected).")
                    continue

                encodings = face_recognition.face_encodings(img_np, face_locations, num_jitters=5)
                if not encodings:
                    skipped += 1
                    st.warning(f"Photo {idx+1}: skipped (could not compute encoding).")
                    continue

                collected_encodings.append(encodings[0])

                photo_fname = f"{safe_name}_{int(time.time())}_{idx}.jpg"
                photo_path = os.path.join(photos_folder, photo_fname)
                img.save(photo_path)
                if first_photo_path is None:
                    first_photo_path = photo_path

            if not collected_encodings:
                st.error("No valid face found in any captured photo. Please try again with clearer, single-face photos.")
            else:
                if len(collected_encodings) < 3:
                    st.info(f"Registered with {len(collected_encodings)} photo(s). For best accuracy, consider re-registering later with 3-5 photos.")

                avg_encoding = np.mean(np.array(collected_encodings), axis=0).tolist()
                student = add_student(
                    name=student_name.strip(),
                    class_id=class_id,
                    photo_path=first_photo_path,
                    encoding_list=avg_encoding
                )
                st.success(f"✅ Registered: {student.name} using {len(collected_encodings)} photo(s), {skipped} skipped")
                st.session_state[photos_key] = []
                st.rerun()

def pick_teacher_and_class(key_prefix):
    teachers = get_all_teachers()
    if not teachers:
        st.info("No teachers have registered yet.")
        return None, None

    teacher_options = {t.display_name: t.id for t in teachers}
    selected_teacher_name = st.selectbox("Select Teacher", options=list(teacher_options.keys()), key=f"{key_prefix}_teacher_select")
    selected_teacher_id = teacher_options[selected_teacher_name]

    classes = get_classes_for_teacher(selected_teacher_id)
    if not classes:
        st.info("This teacher has no classes yet.")
        return selected_teacher_id, None

    class_options = {c.name: c.id for c in classes}
    selected_class_name = st.selectbox("Select Class", options=list(class_options.keys()), key=f"{key_prefix}_class_select")
    selected_class_id_pub = class_options[selected_class_name]

    return selected_teacher_id, selected_class_id_pub

# ---------------- Teacher Portal ----------------
def show_teacher_portal():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["teacher_id"] = None
        st.session_state["teacher_name"] = None

    if not st.session_state["logged_in"]:
        st.title("🧑‍🏫 Teacher Login")
        tab_login, tab_signup = st.tabs(["🔑 Login", "🆕 Create Account"])

        with tab_login:
            login_username = st.text_input("Username", key="login_username")
            login_password = st.text_input("Password", type="password", key="login_password")
            if st.button("Login", type="primary"):
                if not login_username.strip() or not login_password:
                    st.error("Please enter both username and password.")
                else:
                    teacher = authenticate_teacher(login_username.strip(), login_password)
                    if teacher:
                        st.session_state["logged_in"] = True
                        st.session_state["teacher_id"] = teacher.id
                        st.session_state["teacher_name"] = teacher.display_name
                        st.rerun()
                    else:
                        st.error("❌ Invalid username or password.")

        with tab_signup:
            new_display_name = st.text_input("Your name", key="signup_display_name")
            new_username = st.text_input("Choose a username", key="signup_username")
            new_password = st.text_input("Password", type="password", key="signup_password")
            if st.button("Create Account"):
                if not new_username.strip() or not new_password or not new_display_name.strip():
                    st.error("All fields are required.")
                else:
                    teacher = create_teacher(new_username.strip(), new_password, new_display_name.strip())
                    if teacher:
                        st.success("✅ Account created! Please login from the 'Login' tab.")
                    else:
                        st.error("This username is already taken, please choose another.")
        return

    # --- Logged in ---
    user_id = st.session_state["teacher_id"]
    username = st.session_state["teacher_name"]

    with st.sidebar:
        st.success(f"👋 Logged in as: **{username}**")
        if st.button("🚪 Logout"):
            st.session_state["logged_in"] = False
            st.session_state["teacher_id"] = None
            st.session_state["teacher_name"] = None
            st.session_state["portal_mode"] = None
            st.rerun()

    st.title("Classes & Students")

    with st.expander("➕ Create a new class", expanded=True):
        new_class_name = st.text_input("Class name", key="new_class_name")
        if st.button("Create class"):
            if not new_class_name.strip():
                st.error("Please enter a class name.")
            else:
                cls = create_class(name=new_class_name.strip(), teacher_id=user_id)
                st.success(f"✅ Created class: {cls.name} (id={cls.id})")
                if "reload_trigger" not in st.session_state:
                    st.session_state["reload_trigger"] = 0
                st.session_state["reload_trigger"] += 1
                st.rerun()

    classes = get_classes_for_teacher(user_id)
    if not classes:
        st.info("No classes yet. Create one above.")
        return

    selected = st.selectbox(
        "Select class",
        options=[(c.id, c.name) for c in classes],
        format_func=lambda x: x[1],
        key=f"class_select_{st.session_state.get('reload_trigger', 0)}"
    )
    selected_class_id = selected[0] if isinstance(selected, tuple) else selected

    st.subheader(f"Selected class: {dict((c.id, c.name) for c in classes).get(selected_class_id)} (id: {selected_class_id})")

    if st.button("🗑️ Delete this entire class", type="secondary"):
        st.session_state["confirm_delete_class"] = selected_class_id

    if st.session_state.get("confirm_delete_class") == selected_class_id:
        st.warning("⚠️ This will permanently delete this class, all its students, and all attendance history.")
        col_yes, col_no = st.columns([1, 1])
        if col_yes.button("✅ Yes, delete permanently"):
            delete_class(selected_class_id)
            st.session_state["confirm_delete_class"] = None
            if "reload_trigger" not in st.session_state:
                st.session_state["reload_trigger"] = 0
            st.session_state["reload_trigger"] += 1
            st.success("Class deleted.")
            st.rerun()
        if col_no.button("❌ Cancel"):
            st.session_state["confirm_delete_class"] = None
            st.rerun()

    students = get_students_by_class(selected_class_id)
    if not students:
        st.info("No students registered in this class yet. Students can self-register from the Student Portal.")
    else:
        st.write("**Registered Students:**")
        for s in students:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            col1.write(f"👤 {s.name}")
            col2.write("📷 Photo ✅" if s.photo_path else "📷 Photo ❌")
            col3.write("🧬 Face data ✅" if s.encoding_json else "🧬 Face data ❌")
            if col4.button("🗑️ Delete", key=f"del_student_{s.id}"):
                delete_student(s.id)
                st.success(f"{s.name} has been deleted.")
                st.rerun()

    st.markdown("---")
    st.header("Take Attendance (Group Photo)")
    st.caption("Click ONE photo of the whole class. Works accurately even with 40-50 students in frame.")

    group_photo = st.camera_input("Capture classroom photo", key="group_attendance_camera")

    group_threshold = st.slider(
        "Matching threshold (lower = stricter, higher = more lenient)",
        0.35, 0.7, 0.5, 0.01, key="group_threshold"
    )

    if group_photo is not None:
        if st.button("🔍 Detect & Mark Attendance", type="primary"):
            with st.spinner("Detecting faces... this may take a few seconds for large groups"):
                img = Image.open(group_photo).convert("RGB")
                img_np = np.array(img)

                # face_recognition's own HOG-based detector handles multiple
                # faces in a group photo well, without needing a separate
                # TensorFlow-based model (which was the main cause of
                # out-of-memory crashes during deployment).
                face_locations = face_recognition.face_locations(img_np)

                if not face_locations:
                    st.error("No faces detected. Try a clearer, well-lit photo.")
                else:
                    face_encodings = face_recognition.face_encodings(img_np, known_face_locations=face_locations)

                    group_students = get_students_by_class(selected_class_id)
                    known_encodings, known_ids, known_names = [], [], []
                    for s in group_students:
                        if s.encoding_json:
                            try:
                                known_encodings.append(np.array(json.loads(s.encoding_json), dtype='float64'))
                                known_ids.append(s.id)
                                known_names.append(s.name)
                            except Exception:
                                pass

                    # Greedy unique assignment: closest face-student pairs first,
                    # so the same student can never be matched to two different
                    # faces in the photo.
                    candidate_pairs = []
                    if known_encodings:
                        known_enc_array = np.array(known_encodings, dtype='float64')
                        if known_enc_array.ndim == 1:
                            known_enc_array = known_enc_array.reshape(1, -1)
                        for face_idx, enc in enumerate(face_encodings):
                            dists = face_recognition.face_distance(known_enc_array, np.array(enc, dtype='float64'))
                            for student_idx, dist in enumerate(dists):
                                if dist <= group_threshold:
                                    candidate_pairs.append((float(dist), face_idx, student_idx))
                    candidate_pairs.sort(key=lambda x: x[0])

                    assigned_face, assigned_student = {}, set()
                    for dist, face_idx, student_idx in candidate_pairs:
                        if face_idx in assigned_face or student_idx in assigned_student:
                            continue
                        assigned_face[face_idx] = student_idx
                        assigned_student.add(student_idx)

                    present_ids = set()
                    annotated = img.copy()
                    draw = ImageDraw.Draw(annotated)

                    for i, loc in enumerate(face_locations):
                        top, right, bottom, left = loc
                        name_label, matched_id = "Unknown", None

                        if i in assigned_face:
                            student_idx = assigned_face[i]
                            matched_id = known_ids[student_idx]
                            name_label = known_names[student_idx]
                            present_ids.add(matched_id)

                        color = "green" if matched_id else "red"
                        draw.rectangle(((left, top), (right, bottom)), outline=color, width=3)
                        draw.text((left + 4, max(0, top - 16)), name_label, fill=color)

                    st.image(annotated, caption=f"{len(face_locations)} faces detected", width="stretch")

                    session_obj = create_attendance_session(
                        class_id=selected_class_id, photo_path="", threshold=float(group_threshold)
                    )
                    for s in group_students:
                        status = "Present" if s.id in present_ids else "Absent"
                        save_attendance_record(
                            session_id=session_obj.id,
                            student_id=s.id,
                            student_name=s.name,
                            status=status
                        )

                    st.success(f"✅ Attendance saved! {len(present_ids)}/{len(group_students)} students present")

    st.markdown("---")
    st.header("Attendance History")
    st.caption("Pick a past date/session. If a status looks wrong, change it below and click 'Save Changes'.")

    sessions = get_sessions_for_class(selected_class_id)

    if not sessions:
        st.info("No attendance has been recorded for this class yet.")
    else:
        session_options = {
            f"{sess.created_at.strftime('%d %b %Y, %I:%M %p') if sess.created_at else f'Session #{sess.id}'} (id={sess.id})": sess.id
            for sess in sessions
        }
        selected_session_label = st.selectbox("Select a date/session", options=list(session_options.keys()))
        selected_session_id = session_options[selected_session_label]

        records = get_records_for_session(selected_session_id)
        if not records:
            st.info("No records found for this session.")
        else:
            edited_statuses = {}
            for r in records:
                col1, col2 = st.columns([3, 2])
                col1.write(r.student_name)
                edited_statuses[r.id] = col2.selectbox(
                    "Status", ["Present", "Absent"],
                    index=0 if r.status == "Present" else 1,
                    key=f"status_{r.id}",
                    label_visibility="collapsed"
                )

            present_count = sum(1 for v in edited_statuses.values() if v == "Present")
            st.write(f"**{present_count} / {len(records)} present** on this date")

            if st.button("💾 Save Changes", type="primary"):
                for record_id, new_status in edited_statuses.items():
                    update_attendance_status(record_id, new_status)
                st.success("✅ Attendance updated!")
                st.rerun()

# ---------------- Student Portal ----------------
def show_student_portal():
    st.title("🎓 Student Portal")
    tab_register, tab_check = st.tabs(["📝 Register as a Student", "✅ Check My Attendance"])

    with tab_register:
        st.caption("Pick your teacher and class, enter your name, and capture 3-5 clear photos.")
        _, class_id = pick_teacher_and_class("reg")
        if class_id is not None:
            run_registration_flow(class_id, key_prefix="pub_reg")

    with tab_check:
        st.caption("Select your teacher, class, and name to see your attendance record. No login required.")
        _, class_id = pick_teacher_and_class("check")
        if class_id is not None:
            students_pub = get_students_by_class(class_id)
            if not students_pub:
                st.info("No students registered in this class yet.")
            else:
                student_options = {s.name: s.id for s in students_pub}
                selected_student_name = st.selectbox("Select Your Name", options=list(student_options.keys()), key="student_self_select")
                selected_student_id = student_options[selected_student_name]

                history = get_attendance_history_for_student(selected_student_id)
                if not history:
                    st.info("No attendance recorded yet.")
                else:
                    present_count = sum(1 for h in history if h["status"] == "Present")
                    st.write(f"**{present_count} / {len(history)} classes present**")
                    rows = [
                        {"Date": h["date"].strftime("%d %b %Y, %I:%M %p") if h["date"] else "Unknown", "Status": h["status"]}
                        for h in history
                    ]
                    st.table(rows)

# ---------------- Role Selector (very first screen) ----------------
if "portal_mode" not in st.session_state:
    st.session_state["portal_mode"] = None

if st.session_state["portal_mode"] is None:
    st.title("🎓 Face Attendance System")
    st.caption("Please select your role to continue.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧑‍🏫  I am a Teacher", use_container_width=True, type="primary"):
            st.session_state["portal_mode"] = "teacher"
            st.rerun()
    with col2:
        if st.button("🎓  I am a Student", use_container_width=True):
            st.session_state["portal_mode"] = "student"
            st.rerun()

elif st.session_state["portal_mode"] == "teacher":
    with st.sidebar:
        if st.button("⬅️ Back to role selection"):
            st.session_state["portal_mode"] = None
            st.session_state["logged_in"] = False
            st.rerun()
    show_teacher_portal()

elif st.session_state["portal_mode"] == "student":
    with st.sidebar:
        if st.button("⬅️ Back to role selection"):
            st.session_state["portal_mode"] = None
            st.rerun()
    show_student_portal()
