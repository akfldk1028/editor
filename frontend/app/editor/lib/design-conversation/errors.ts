const MESSAGES: Record<string, string> = {
  conversation_processing_failed: '요청을 처리하다 멈췄어요. 기존 메시지는 저장되어 있어요. 계속하려면 원하는 내용을 새 메시지로 다시 보내 주세요.',
  conversation_model_timeout: '에이전트의 응답이 늦어 대기가 끝났어요. 기존 메시지는 저장되어 있어요. 계속하려면 원하는 내용을 새 메시지로 다시 보내 주세요.',
  conversation_program_reconciliation_required: '공간 구성의 반영 결과를 확인해야 해요. 다음 메시지를 처리하기 전에 이전 반영 결과부터 확인해요. 조건이 바뀌었다면 현재 조건과 결과도 확인해 주세요.',
  conversation_step_limit: '한 번에 처리할 수 있는 범위에 도달했어요. 이어서 할 내용을 새 메시지로 보내 주세요.',
  conversation_interrupted: '대화 처리가 중단됐어요. 기존 메시지는 저장되어 있어요. 계속하려면 원하는 내용을 새 메시지로 다시 보내 주세요.',
  conversation_scheduling_failed: '대화 처리를 시작하지 못했어요. 기존 메시지는 저장되어 있어요. 잠시 후 원하는 내용을 새 메시지로 다시 보내 주세요.',
}

export function conversationErrorText(error: string | null | undefined): string | null {
  if (!error) return null
  return MESSAGES[error] ?? '대화를 처리하지 못했어요. 현재 상태를 확인하고 원하는 내용을 새 메시지로 다시 보내 주세요.'
}
