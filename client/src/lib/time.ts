/** 서버의 시각(ISO)을 이 기기의 시간대로 "14:05"처럼 보인다. 수업 중 화면이라 날짜는 붙이지 않는다. */
const CLOCK = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

export function clockTime(iso: string): string {
	return CLOCK.format(new Date(iso));
}
