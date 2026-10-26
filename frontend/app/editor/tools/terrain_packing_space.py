"""Account for PMTiles' temporary payload and final archive on their actual volumes."""


def require_capacity(free_by_volume,final_volume,spool_volume,payload_bound,*,reserve=20*1024**3,margin=128*1024**2):
    if min(payload_bound,reserve,margin)<0:raise ValueError('Negative storage budget')
    required={volume:reserve+margin for volume in (final_volume,spool_volume)}
    for volume in (final_volume,spool_volume):required[volume]+=payload_bound
    for volume,minimum in required.items():
        if free_by_volume[volume]<minimum:
            raise OSError(f'Packing volume {volume} needs {minimum} bytes; available {free_by_volume[volume]}')
    return required
