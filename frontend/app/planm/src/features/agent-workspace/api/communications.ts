export interface Communication {
  id:string;task_id:string;tool:string;agent:string|null;state:string;
  request_text:string|null;response_text:string|null;transport:'a2a'|'unknown';truncated:boolean;
}
export interface Communications {
  communications:Communication[];communications_available:boolean;communications_truncated:boolean;
}
export function parseCommunications(value:Record<string,unknown>):Communications {
  const keys=['communications','communications_available','communications_truncated'];
  if(keys.every(key=>!(key in value)))return {communications:[],communications_available:false,communications_truncated:false};
  const rows=value.communications;
  if(typeof value.communications_available!=='boolean'||typeof value.communications_truncated!=='boolean'||
    !Array.isArray(rows)||rows.length>100||rows.some(row=>!row||typeof row!=='object'||
      !['id','task_id','tool','state'].every(key=>typeof row[key]==='string')||
      !(row.agent===null||typeof row.agent==='string')||
      !['request_text','response_text'].every(key=>row[key]===null||(typeof row[key]==='string'&&Array.from(row[key]).length<=8000))||
      !['a2a','unknown'].includes(row.transport)||typeof row.truncated!=='boolean')||
    new Set(rows.map(row=>row.id)).size!==rows.length||
    (!value.communications_available&&(rows.length>0||value.communications_truncated)))
    throw new Error('대화 기록 응답 형식이 올바르지 않습니다.');
  return {communications:rows,communications_available:value.communications_available,communications_truncated:value.communications_truncated};
}
