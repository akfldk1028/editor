import base64

import pytest

from backend.app.adapters.workspace.team import make_task


@pytest.mark.parametrize('mime', [
    'application/json', 'application/xml', 'application/javascript',
    'application/typescript', 'application/x-yaml', 'application/yaml',
    'application/csv', 'application/x-python', 'text/plain',
])
def test_upload_mime_types_reach_the_agent_as_text(mime):
    task = make_task('Review this attachment', [{
        'name': 'proposal.txt', 'type': mime,
        'content': base64.b64encode(b'proposal: needs review').decode(),
    }])
    assert task.content == [
        'Review this attachment',
        '\nAttachment: proposal.txt\nproposal: needs review',
    ]


def test_binary_attachment_cannot_be_interpreted_as_text():
    with pytest.raises(ValueError, match='UTF-8 text file or image'):
        make_task('Review', [{
            'name': 'binary.exe', 'type': 'application/octet-stream',
            'content': base64.b64encode(b'\x00\xff').decode(),
        }])
