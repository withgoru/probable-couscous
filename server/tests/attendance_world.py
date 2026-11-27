"""003 출석 테스트가 함께 쓰는 도구: 강좌 만들기, 명단 넣기, 입장한 학생 클라이언트."""

import re

from conftest import ORIGIN


def make_classroom(world, owner="kim", name="웹 프로그래밍", section=None):
    prof = world.client(owner)
    res = prof.post("/api/classrooms", json={"name": name, "section_name": section}, headers=ORIGIN)
    assert res.status_code == 201, res.text
    return prof, res.json()["id"]


def enroll(prof, classroom_id, email, no="1", name="김철수"):
    res = prof.post(
        f"/api/classrooms/{classroom_id}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def invite_token(prof, classroom_id):
    return prof.get(f"/api/classrooms/{classroom_id}/invite").json()["token"]


def entered_student(world, prof, classroom_id, email, no=None, name="김철수"):
    """명단에 넣고 초대 링크로 입장까지 마친 학생 클라이언트. 학번을 주지 않으면 이메일에서 만든다(겹치지 않게)."""
    enroll(prof, classroom_id, email, no=no or email.split("@")[0], name=name)
    token = invite_token(prof, classroom_id)
    student = world.client()
    assert student.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN).json()["next"] == "code"
    world.app.state.mail_worker.process_due()
    code = re.search(r"\b(\d{6})\b", world.app.state.mailer.sent[-1].text).group(1)
    res = student.post(f"/api/join/{token}/code", json={"email": email, "code": code}, headers=ORIGIN)
    assert res.status_code == 200, res.text
    assert student.post(f"/api/join/{token}/enter", headers=ORIGIN).status_code == 200
    return student
