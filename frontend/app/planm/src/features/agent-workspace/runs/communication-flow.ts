import type {Communication} from '../api/communications';

export interface CommunicationEdge {agent:string;calls:number;responses:number}

export function communicationFlow(records:Communication[]) {
  const edges=new Map<string,CommunicationEdge>();
  let unknown=0;
  for(const record of records){
    if(!record.agent){unknown++;continue;}
    const edge=edges.get(record.agent)??{agent:record.agent,calls:0,responses:0};
    edge.calls++;
    if(record.response_text!==null)edge.responses++;
    edges.set(record.agent,edge);
  }
  return {edges:[...edges.values()],unknown};
}
