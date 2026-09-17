import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';

/** 仅在开发环境经 main.tsx 动态 import 启动，不进入生产构建产物 */
export const worker = setupWorker(...handlers);
