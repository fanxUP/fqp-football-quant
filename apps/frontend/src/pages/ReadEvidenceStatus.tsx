import type { ReadOnlyResource } from '../features/command-center/useReadOnlyResource';
import { formatTimestamp } from '../shared/utils';

/** Receipt time describes this GET, not the source's generation time. */
export default function ReadEvidenceStatus({ resource, label, note }: {
  resource: ReadOnlyResource<unknown> & { refresh: () => Promise<void> };
  label: string;
  note?: string;
}) {
  return <div className="be-status">
    <span>{resource.receivedAt === null ? (resource.loading ? '读取中…' : '尚无成功数据') : `接收时间 ${formatTimestamp(new Date(resource.receivedAt).toISOString())}`}{note && ` · ${note}`}</span>
    <button type="button" disabled={resource.loading} onClick={() => void resource.refresh()}>{label}</button>
    {resource.error && <p role="alert" className="be-error">{resource.error} · {resource.data === null ? '本查询尚无成功数据，请重试' : '保留本查询上次成功数据'}</p>}
  </div>;
}
