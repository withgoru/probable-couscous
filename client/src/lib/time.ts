/** 서버의 시각(ISO)을 이 기기의 시간대로 "14:05"처럼 보인다. 수업 중 화면이라 날짜는 붙이지 않는다. */
const CLOCK = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

export function clockTime(iso: string): string {
	return CLOCK.format(new Date(iso));
}

const DATE_TIME = new Intl.DateTimeFormat('ko-KR', {
	month: 'long',
	day: 'numeric',
	hour: '2-digit',
	minute: '2-digit',
	hourCycle: 'h23'
});

/** 서버의 시각(ISO)을 "3월 4일 14:05"처럼 보인다. 수업 전에 준비한 자료처럼 날짜가 필요한 곳에 쓴다. */
export function dateTime(iso: string): string {
	return DATE_TIME.format(new Date(iso));
}
