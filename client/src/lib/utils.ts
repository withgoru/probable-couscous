import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** 클래스 이름을 합치고 Tailwind 클래스가 겹치면 뒤의 것을 남긴다 (shadcn-svelte 컴포넌트가 쓴다) */
export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

// shadcn-svelte 컴포넌트의 속성 타입 도우미
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChild<T> = T extends { child?: any } ? Omit<T, 'child'> : T;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChildren<T> = T extends { children?: any } ? Omit<T, 'children'> : T;
export type WithoutChildrenOrChild<T> = WithoutChildren<WithoutChild<T>>;
export type WithElementRef<T, U extends HTMLElement = HTMLElement> = T & { ref?: U | null };
