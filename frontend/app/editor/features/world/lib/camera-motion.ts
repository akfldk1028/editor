/** Pose stability is authoritative: Cesium can emit moveStart without a matching
 * moveEnd after terrain correction/setView, leaving an event-only gate stuck. */
export class CameraMotion {
  private pose: readonly number[] | undefined
  private changedAt = -Infinity

  update(now: number, pose: readonly number[]): boolean {
    if (this.pose && pose.some((value, i) => Math.abs(value - this.pose![i]!) > 1e-9)) this.changedAt = now
    this.pose = pose
    return now - this.changedAt < 200
  }
}
