"""Match a requested ramp turn to its actual centreline, independent of labels."""
import math


def turn_degrees(ramp):
    line=ramp.get('centerline')
    if line is None or line.is_empty:
        return None
    points=list(line.coords)
    headings=[math.atan2(b[1]-a[1],b[0]-a[0]) for a,b in zip(points,points[1:])
              if math.hypot(b[0]-a[0],b[1]-a[1])>1e-8]
    if len(headings)<2:
        return 0.
    turn=sum(math.atan2(math.sin(b-a),math.cos(b-a)) for a,b in zip(headings,headings[1:]))
    return abs(math.degrees(turn))


def matches_turn(ramp, requested):
    measured=turn_degrees(ramp)
    return measured is not None and math.isclose(measured,requested,abs_tol=.1)
