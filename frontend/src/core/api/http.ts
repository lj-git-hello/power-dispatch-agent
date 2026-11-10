/**
 * http —— 通用 Axios 实例。
 *
 * - baseURL 走 /api（开发期由 Vite 代理到后端）；
 * - 请求拦截自动从 localStorage 读取 JWT 并挂载 Bearer；
 * - 响应拦截统一归一化错误，便于上层处理（401 等）。
 */

import axios, { AxiosError, type AxiosInstance } from 'axios'

/** localStorage 中 JWT 的键名 */
export const TOKEN_STORAGE_KEY = 'access_token'

/** 归一化后的错误结构 */
export interface ApiError {
  status: number
  message: string
  raw: unknown
}

function readToken(): string {
  return localStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
}

export const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截：挂载鉴权头
http.interceptors.request.use((config) => {
  const token = readToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：只返回响应体，错误归一化后继续抛出
http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string }>) => {
    const apiError: ApiError = {
      status: error.response?.status ?? 0,
      message: error.response?.data?.detail ?? error.message ?? '网络请求失败',
      raw: error,
    }
    return Promise.reject(apiError)
  },
)

/** 供登录流程保存 JWT。 */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

/** 退出登录时清除 JWT。 */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}
