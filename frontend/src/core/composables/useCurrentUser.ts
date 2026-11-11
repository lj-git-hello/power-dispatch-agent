/**
 * useCurrentUser —— 当前登录用户身份（通用、跨业务）。
 *
 * 由工作台外壳在初始化 / 切换身份时写入；卡片等深层组件据此做权限判定。
 * 仅持有前端展示所需的最小身份信息，不涉及任何业务概念。
 */

import { reactive } from 'vue'

/** 通用用户角色（仅作字符串透传，具体取值由各业务 IAM 决定） */
interface CurrentUserState {
  userId: string
  role: string
}

const currentUser = reactive<CurrentUserState>({
  userId: '',
  role: '',
})

/** 设置当前用户身份。 */
function setCurrentUser(userId: string, role: string) {
  currentUser.userId = userId
  currentUser.role = role
}

/** 是否包含任一给定角色。 */
function hasAnyRole(...roles: string[]): boolean {
  return roles.includes(currentUser.role)
}

export function useCurrentUser() {
  return {
    currentUser,
    setCurrentUser,
    hasAnyRole,
  }
}