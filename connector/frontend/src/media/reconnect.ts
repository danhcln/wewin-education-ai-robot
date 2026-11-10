export function reconnectDelay(attempt:number){return Math.min(15000,1000*2**Math.min(10,Math.max(0,attempt)));}
export const MAX_RECONNECT_ATTEMPTS=12;
