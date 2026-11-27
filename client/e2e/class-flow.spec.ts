import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Browser, type Page } from "@playwright/test";
import { expectNoAxeViolations, noTransitions } from "./a11y-helpers";
import { controlSockets } from "./class-helpers";
import {
  classroomWith,
  lastCode,
  requestCode,
  student,
  typeCode,
  type Student,
} from "./helpers";

// 002 T028: 수업 한 번의 흐름 전체. 교수 화면·프로젝터·학생 두 명이 서로 다른 브라우저 컨텍스트에서 같은 서버에 붙는다.
// 시작 → 넘기기(학생·프로젝터가 따라옴) → 비공개 묶음은 따라가기만 → 수업 중 공개 → 학생이 끝까지 넘김 → 교수 화면으로
// → 보내기·거두기 → 학생 연결을 끊었다 붙임(놓친 항목 회복) → 종료 → 다시 보기
// (AC9, AC15, AC19, AC25, AC26, AC27, AC28, AC31, AC35, AC37, AC38, AC39, AC48, C12, C13)
const DECK_ZIP = fileURLToPath(
  new URL("../../server/tests/fixtures/deck-small.zip", import.meta.url),
);
const LAPTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };
const PRIVATE_LINE =
  "교수 화면 따라가는 중 · 교수님이 슬라이드를 공개하면 직접 넘겨 볼 수 있습니다.";

const hashOf = (page: Page, title: string) =>
  page
    .frameLocator(`iframe[title="${title}"]`)
    .locator("body")
    .evaluate(() => location.hash);

/** 슬라이드가 그 위치를 그려 넘길 수 있게 된 뒤에 누른다(그 전에 누르면 화면이 받지 않는다). */
async function press(page: Page, name: string) {
  const button = page.getByRole("button", { name, exact: true });
  await expect(button).toHaveAttribute("aria-disabled", "false");
  await button.click();
}

/** 학생 한 명: 자기 브라우저(휴대폰 크기)에서 이메일·코드로 입장해 대기 화면까지 간다. */
async function phoneOf(
  browser: Browser,
  token: string,
  who: Student,
  watchSockets = false,
) {
  const context = await browser.newContext({ viewport: PHONE });
  const page = await context.newPage();
  const sockets = watchSockets ? await controlSockets(page) : null;
  await requestCode(page, token, who.email);
  await typeCode(page, await lastCode(who.email));
  await page.getByRole("button", { name: "확인하고 입장" }).click();
  await expect(
    page.getByText(
      "지금 진행 중인 수업이 없습니다. 수업이 시작되면 이 화면이 바뀝니다.",
    ),
  ).toBeVisible();
  await noTransitions(page);
  return { context, page, sockets };
}

test("수업 한 번: 시작부터 다시 보기까지 교수·프로젝터·학생 두 명이 함께 움직인다", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const [kim, lee] = [
    student("flow-a", "김철수", "20240001"),
    student("flow-b", "이영희", "20240002"),
  ];
  const room = await classroomWith([kim, lee], `수업 흐름 ${Date.now()}`);
  const session = await (
    await room.api.post(`/api/classrooms/${room.id}/sessions`, {
      data: { title: "5주차 1회차" },
    })
  ).json();
  const upload = await room.api.put(
    `/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`,
    {
      headers: { "Content-Type": "application/zip" },
      data: readFileSync(DECK_ZIP),
    },
  );
  expect(upload.status(), await upload.text()).toBe(200);
  const serverState = async () =>
    (
      await room.api.get(`/api/class/${room.id}/sessions/${session.id}/live`)
    ).json();

  // 실패해도 연 브라우저를 닫는다(다른 테스트에 다시 붙는 연결이 남지 않게)
  const contexts: { close: () => Promise<void> }[] = [];
  try {
    // 학생 두 명이 수업 전에 들어와 기다린다
    const a = await phoneOf(browser, room.token, kim);
    contexts.push(a.context);
    const b = await phoneOf(browser, room.token, lee, true);
    contexts.push(b.context);

    // 교수가 관리 페이지에서 수업을 시작하면 교수 수업 화면이 열린다(AC9)
    const desk = await browser.newContext({ viewport: LAPTOP });
    contexts.push(desk);
    const teacher = await desk.newPage();
    await teacher.goto("/api/auth/github/login");
    await teacher.waitForURL("**/courses");
    await teacher.goto(`/courses/${room.id}/admin`);
    await teacher.getByRole("button", { name: "수업 시작" }).click();
    await expect(teacher).toHaveURL(new RegExp(`/courses/${room.id}/live$`));
    await noTransitions(teacher);
    await expect(
      teacher.getByRole("heading", { level: 1, name: "5주차 1회차" }),
    ).toBeVisible();
    expect((await serverState()).session.status).toBe("live"); // 회차가 '진행 중'이 됐다

    // 프로젝터 창을 연다(AC19)
    const popup = desk.waitForEvent("page");
    await teacher.getByRole("button", { name: "프로젝터 화면 열기" }).click();
    const projector = await popup;
    await noTransitions(projector);
    await expect.poll(() => hashOf(projector, "슬라이드")).toMatch(/^#\/1/);
    await expect(projector.getByRole("button", { name: "다음" })).toHaveCount(
      0,
    ); // 슬라이드만, 직접 넘기지 못한다

    // 학생 화면은 새로 고치지 않고 수업 화면이 된다(AC23). 새 묶음은 비공개라 따라가기만 한다(AC27)
    for (const phone of [a.page, b.page]) {
      await expect(phone.getByText(PRIVATE_LINE)).toBeVisible();
      await expect(phone.getByRole("button", { name: "다음" })).toHaveCount(0);
      await expect.poll(() => hashOf(phone, "수업 슬라이드")).toMatch(/^#\/1/);
    }
    await expect(
      teacher.getByText("따라가는 중 2명 · 직접 넘겨 보는 중 0명"),
    ).toBeVisible(); // AC15

    // 교수가 넘기면 프로젝터와 학생이 따라온다(AC20, AC25)
    await press(teacher, "다음");
    await expect.poll(() => hashOf(projector, "슬라이드")).toMatch(/^#\/2/);
    for (const phone of [a.page, b.page])
      await expect.poll(() => hashOf(phone, "수업 슬라이드")).toMatch(/^#\/2/);
    // 비공개 묶음에서는 슬라이드 안에서 →를 눌러도 움직이지 않는다(AC27)
    await a.page
      .frameLocator('iframe[title="수업 슬라이드"]')
      .locator("body")
      .press("ArrowRight");
    await expect(a.page.getByText(PRIVATE_LINE)).toBeVisible();
    expect(await hashOf(a.page, "수업 슬라이드")).toMatch(
      /^#\/2(\?clicks=0)?$/,
    );

    // 수업 중에 관리 페이지에서 공개한다: 학생 화면에 이전·다음이 나타난다(AC47, AC48)
    const admin = await desk.newPage();
    await admin.goto(`/courses/${room.id}/admin`);
    await admin.getByRole("switch", { name: "학생에게 공개" }).click();
    await expect(
      admin.getByRole("switch", { name: "학생에게 공개" }),
    ).toHaveAttribute("aria-checked", "true");
    await expect.poll(async () => (await serverState()).deck.public).toBe(true); // 화면은 먼저 바뀐다. 서버에 남은 뒤 닫는다
    await admin.close();
    for (const phone of [a.page, b.page])
      await expect(phone.getByRole("button", { name: "다음" })).toBeVisible();

    // 학생 A가 넘기면 따라가기가 풀리고 묶음의 끝까지 간다(AC26). B와 프로젝터는 교수를 따라간다
    for (const expected of [
      /^#\/2\?clicks=1/,
      /^#\/2\?clicks=2/,
      /^#\/2\?clicks=3/,
      /^#\/3/,
      /^#\/4(\?clicks=0)?$/,
      /^#\/4\?clicks=1/,
    ]) {
      await press(a.page, "다음");
      await expect
        .poll(() => hashOf(a.page, "수업 슬라이드"))
        .toMatch(expected);
    }
    await expect(a.page.getByRole("button", { name: "다음" })).toHaveAttribute(
      "aria-disabled",
      "true",
    ); // 묶음의 끝
    await expect(
      a.page.getByText("직접 넘겨 보는 중 · 교수 화면은 2번 슬라이드입니다."),
    ).toBeVisible();
    await expect
      .poll(() => hashOf(b.page, "수업 슬라이드"))
      .toMatch(/^#\/2(\?clicks=0)?$/);
    await expect
      .poll(() => hashOf(projector, "슬라이드"))
      .toMatch(/^#\/2(\?clicks=0)?$/); // 학생이 넘겨도 프로젝터는 그대로
    expect((await serverState()).current).toEqual({ slide: 2, click: 0 }); // 수업 위치도 그대로
    await expect(
      teacher.getByText("따라가는 중 1명 · 직접 넘겨 보는 중 1명"),
    ).toBeVisible(); // AC15
    await expectNoAxeViolations(a.page, "직접 넘겨 보는 학생 화면");

    // 교수가 넘기면 B와 프로젝터는 따라오고, 직접 넘겨 보는 A는 보던 곳에 머문다(AC26)
    await press(teacher, "다음"); // (2, 1)
    await expect
      .poll(() => hashOf(b.page, "수업 슬라이드"))
      .toMatch(/^#\/2\?clicks=1/);
    await expect
      .poll(() => hashOf(projector, "슬라이드"))
      .toMatch(/^#\/2\?clicks=1/);
    await expect(
      a.page.getByText("직접 넘겨 보는 중 · 교수 화면은 2번 슬라이드입니다."),
    ).toBeVisible();
    expect(await hashOf(a.page, "수업 슬라이드")).toMatch(/^#\/4\?clicks=1/);

    // '교수 화면으로'를 누르면 교수의 지금 위치로 가서 다시 따라간다(AC28)
    await a.page.getByRole("button", { name: "교수 화면으로" }).click();
    await expect(
      a.page.getByText("교수 화면 따라가는 중", { exact: true }),
    ).toBeVisible();
    await expect
      .poll(() => hashOf(a.page, "수업 슬라이드"))
      .toMatch(/^#\/2\?clicks=1/);
    await expect(
      teacher.getByText("따라가는 중 2명 · 직접 넘겨 보는 중 0명"),
    ).toBeVisible();

    // 보내기와 거두기(AC31, AC33, AC35)
    const panel = teacher.getByRole("region", { name: "메시지·자료 보내기" });
    await panel.getByLabel("글").fill("실습 1 안내");
    await panel.getByRole("button", { name: "학생에게 보내기" }).click();
    await panel.getByLabel("글").fill("잘못 보낸 글");
    await panel.getByRole("button", { name: "학생에게 보내기" }).click();
    for (const phone of [a.page, b.page]) {
      await expect(phone.getByRole("list", { name: "자료" })).toContainText(
        "실습 1 안내",
      );
      await expect(phone.getByRole("list", { name: "자료" })).toContainText(
        "잘못 보낸 글",
      );
    }
    await panel.getByRole("button", { name: "거두기: 잘못 보낸 글" }).click();
    await teacher
      .getByRole("alertdialog")
      .getByRole("button", { name: "거두기" })
      .click();
    for (const phone of [a.page, b.page])
      await expect(phone.getByRole("list", { name: "자료" })).not.toContainText(
        "잘못 보낸 글",
      );
    // 교수 목록에는 최근 것이 맨 위에 남고, 거둔 항목은 그렇게 표시된다(AC31, AC35)
    const sent = panel.getByRole("list", { name: "보낸 항목" });
    await expect(sent.getByRole("listitem").first()).toContainText(
      "잘못 보낸 글",
    );
    await expect(sent.getByRole("listitem").first()).toContainText(
      "거둔 항목 · 학생에게 보이지 않습니다.",
    );
    await expect(sent.getByRole("listitem").nth(1)).toContainText(
      "실습 1 안내",
    );

    // 학생 B의 연결이 끊긴 동안 교수가 넘기고 보낸다. 다시 붙으면 교수 위치와 놓친 항목을 되찾는다(C12)
    await b.sockets!.drop();
    await expect(
      b.page.getByText("연결이 끊겼습니다. 다시 연결하는 중…"),
    ).toBeVisible();
    await press(teacher, "다음"); // (2, 2)
    await expect
      .poll(async () => (await serverState()).current)
      .toEqual({ slide: 2, click: 2 });
    await expect
      .poll(() => hashOf(projector, "슬라이드"))
      .toMatch(/^#\/2\?clicks=2/);
    await panel.getByLabel("글").fill("끊긴 동안 보낸 글");
    await panel.getByRole("button", { name: "학생에게 보내기" }).click();
    await expect(a.page.getByRole("list", { name: "자료" })).toContainText(
      "끊긴 동안 보낸 글",
    );
    await b.sockets!.restore();
    await expect(
      b.page.getByText("연결이 끊겼습니다. 다시 연결하는 중…"),
    ).toHaveCount(0, { timeout: 20_000 });
    await expect(b.page.getByRole("list", { name: "자료" })).toContainText(
      "끊긴 동안 보낸 글",
    );
    await expect
      .poll(() => hashOf(b.page, "수업 슬라이드"))
      .toMatch(/^#\/2\?clicks=2/);

    // 수업을 끝낸다: 교수는 관리 페이지로, 학생은 새로 고치지 않고 같은 회차의 다시 보기로(AC37, AC38)
    await teacher.getByRole("button", { name: "수업 종료" }).click();
    const confirm = teacher.getByRole("alertdialog");
    await expect(confirm).toContainText(
      "학생은 슬라이드와 받은 자료를 계속 볼 수 있습니다.",
    ); // 공개 묶음
    await confirm.getByRole("button", { name: "수업 종료" }).click();
    await expect(teacher).toHaveURL(new RegExp(`/courses/${room.id}/admin$`));
    expect((await serverState()).session.status).toBe("ended");
    for (const phone of [a.page, b.page]) {
      await expect(
        phone.locator("p:not([data-class-status])", {
          hasText: "수업이 끝났습니다.",
        }),
      ).toBeVisible();
      await expect(
        phone.getByRole("heading", { level: 1, name: "5주차 1회차 다시 보기" }),
      ).toBeVisible();
    }

    // 다시 보기: 거두지 않은 항목이 보이고, 공개 묶음이라 끝까지 넘긴다(AC39)
    for (const phone of [a.page, b.page]) {
      const replayList = phone.getByRole("list", { name: "자료" });
      await expect(replayList).toContainText("실습 1 안내");
      await expect(replayList).toContainText("끊긴 동안 보낸 글");
      await expect(replayList).not.toContainText("잘못 보낸 글");
    }
    await expect
      .poll(() => hashOf(a.page, "다시 보는 슬라이드"))
      .toMatch(/^#\/2\?clicks=2/); // 보던 곳(교수의 마지막 위치)
    for (const expected of [
      /^#\/2\?clicks=3/,
      /^#\/3/,
      /^#\/4(\?clicks=0)?$/,
      /^#\/4\?clicks=1/,
    ]) {
      await press(a.page, "다음");
      await expect
        .poll(() => hashOf(a.page, "다시 보는 슬라이드"))
        .toMatch(expected);
    }
    await expect(a.page.getByRole("button", { name: "다음" })).toHaveAttribute(
      "aria-disabled",
      "true",
    ); // 묶음의 끝
    await expectNoAxeViolations(a.page, "수업이 끝난 뒤의 다시 보기");

    // 지난 회차 목록에 끝난 회차가 있고, 다시 열 수 있다(AC39)
    await a.page.getByRole("button", { name: "지난 회차 목록으로" }).click();
    const past = a.page.getByRole("list", { name: "지난 회차" });
    await expect(
      past.getByRole("button", { name: "5주차 1회차 다시 보기" }),
    ).toBeVisible();
  } finally {
    for (const context of contexts) await context.close().catch(() => {});
  }
});
