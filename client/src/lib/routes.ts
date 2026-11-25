/** 수업 중 화면(교수 수업 화면, 프로젝터 화면). 공통 메뉴바를 그리지 않는다(002 AC12, AC21, screens.md). */
export function isClassScreen(pathname: string): boolean {
	return /^\/courses\/\d+\/(live|projector)\/?$/.test(pathname);
}
