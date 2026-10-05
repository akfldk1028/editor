import type { ProjectBinding } from './projects'
import { object, type SpecialistRequest } from './specialist-review'

function DeclaredFields({ value, title }: { value: unknown; title: string }) {
  if (!object(value)) return null
  const fields = Object.entries(value).filter(([, field]) =>
    ['string', 'number', 'boolean'].includes(typeof field),
  )
  if (!fields.length) return null
  return (
    <div className="mt-2">
      <h4 className="font-medium">{title}</h4>
      <ul className="break-all">
        {fields.map(([key, field]) => (
          <li key={key}>
            {key}: {String(field)}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function SpecialistReviewPreview({
  request,
  project,
}: {
  request: SpecialistRequest
  project: ProjectBinding
}) {
  return (
    <div data-testid="specialist-review-preview" className="space-y-3">
      <p className="text-sm">
        연결 프로젝트: {project.owner_project_id} · {project.branch_id}
      </p>
      <p className="text-sm text-(--color-text-secondary)">
        가져온 요청의 컨텍스트와 참조 파일을 그대로 전달합니다. 파일 내용이 현재 설계에서 자동
        추출되거나 최신 상태라고 보증하는 것은 아닙니다. 프로젝트 컨텍스트 버전과 입력 자료의 버전은
        서로 다를 수 있습니다.
      </p>
      {request.specialist_reviews.map((item) => {
        const input = object(item.args.request) ? item.args.request : item.args
        const refs = [input.source_refs, input.source_assets, input.sources].flatMap((rows) =>
          Array.isArray(rows) ? rows.filter(object) : [],
        )
        return (
          <article
            key={item.tool}
            className="rounded border border-(--color-border-default) p-3 text-sm"
          >
            <h3 className="font-medium">
              {
                (
                  {
                    systems: '설비·구조',
                    domain_expert: '전문 분야',
                    interior: '인테리어',
                  } as Record<string, string>
                )[item.agent]
              }{' '}
              · {item.tool}
            </h3>
            <h4 className="font-medium mt-2">요청이 선언한 프로젝트 컨텍스트</h4>
            <ul>
              {Object.entries(item.source_versions).map(([key, revision]) => (
                <li key={key}>
                  {key} · r{revision}
                </li>
              ))}
            </ul>
            <DeclaredFields title="입력 자료의 선언 버전" value={input.expected_source_versions} />
            <DeclaredFields title="입력 자료의 원본 버전" value={input.source_versions} />
            <DeclaredFields title="입력 자료의 프로젝트·브랜치" value={input.source_identity} />
            <DeclaredFields title="담당 에이전트가 선언한 원본 결속" value={input.source_binding} />
            {refs.length > 0 && (
              <div className="mt-2">
                <h4 className="font-medium">실제 전달된 참조 자료</h4>
                <ul aria-label="요청에 포함된 참조 파일" className="space-y-2 break-all">
                  {refs.map((ref, index) => (
                    <li key={index}>
                      <span>
                        {typeof ref.id === 'string'
                          ? ref.id
                          : typeof ref.role === 'string'
                            ? ref.role
                            : '참조'}
                        : {typeof ref.path === 'string' ? ref.path : '요청에 포함된 자료'}
                      </span>
                      {['owner', 'revision', 'sha256', 'scope', 'selection_status'].map((key) =>
                        ['string', 'number'].includes(typeof ref[key]) ? (
                          <div key={key}>
                            {key}: {String(ref[key])}
                          </div>
                        ) : null,
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
