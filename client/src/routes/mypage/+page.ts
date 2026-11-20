import { fetchMySummary } from '#lib/api.js';
import type { PageLoad } from './$types';

export const load: PageLoad = ({ fetch }) => fetchMySummary(fetch);
