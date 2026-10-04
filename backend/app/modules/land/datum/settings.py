from dataclasses import dataclass
import math


@dataclass(frozen=True)
class DatumSettings:
    edge_subsample: bool = True
    edge_subsample_threshold_m: float = 10.0
    edge_subsample_step_m: float = 5.0
    median_filter: bool = True
    median_filter_window: int = 3

    def __post_init__(self):
        for value in (self.edge_subsample_threshold_m, self.edge_subsample_step_m):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('datum sampling distances must be finite and positive')
        if type(self.median_filter_window) is not int or self.median_filter_window < 1:
            raise ValueError('datum median window must be a positive integer')
        if type(self.edge_subsample) is not bool or type(self.median_filter) is not bool:
            raise ValueError('datum sampling flags must be booleans')
