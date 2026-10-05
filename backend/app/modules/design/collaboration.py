"""Project-bound projection of recorded Orchestrator communications for the design UI."""


def recorded_transcript(project_id, run):
    participants = {}
    messages = []
    for row in run['communications']:
        peer = row['agent'] or 'unrecorded_agent'
        participants['orchestrator'] = dict(agent_id='orchestrator', name='Orchestrator',
                                            role='Execution owner', port=0, tone='orchestrator')
        participants[peer] = dict(agent_id=peer, name=peer, port=0, tone='orchestrator',
                                 role='Recorded A2A peer' if row['transport'] == 'a2a' else 'Transport not recorded')
        metadata = {key: row[key] for key in ('task_id', 'tool', 'state', 'transport', 'truncated')}
        metadata['source'] = 'orchestrator_run_receipt'
        state = row['state']
        status = ('fail' if any(word in state for word in ('failed', 'error', 'rejected'))
                  else 'check' if any(word in state for word in ('blocked', 'pending', 'partial')) else 'info')
        for direction in ('request', 'response'):
            text = row[f'{direction}_text']
            if text is None:
                continue
            sender, target = ('orchestrator', peer) if direction == 'request' else (peer, 'orchestrator')
            messages.append(dict(
                id=f"{row['id']}:{direction}", step=len(messages) + 1, timestamp='',
                from_agent=sender, to_agent=target, sender_title=sender, sender_role=row['transport'],
                action_type='info', title=f"{row['tool']} / {direction} / {state}",
                message=text, payload=dict(metadata), status=status,
            ))
    return dict(
        benchmark='Editor project run', project_id=project_id, session_id=run['run_id'],
        pnu='', parcel_address='', timestamp='', participants=list(participants.values()), messages=messages,
        verdict=run['status'], goal=run['goal'], pending_input=run['pending_input'],
        receipt_task_ids=run['receipt_task_ids'], available=run['communications_available'],
        truncated=run['communications_truncated'] or any(row['truncated'] for row in run['communications']),
        elapsed_seconds=0, metrics={'timing_available': False}, source='orchestrator_run_receipt',
    )


def recorded_bus_events(transcript, limit):
    return [dict(timestamp=row['timestamp'], from_agent=row['from_agent'], to_agent=row['to_agent'],
                 message=row['message'], event_type=row['action_type'],
                 metadata={**row['payload'], 'step': row['step'], 'status': row['status'],
                           'sender_title': row['sender_title'], 'sender_role': row['sender_role']})
            for row in transcript['messages'][-limit:]]
