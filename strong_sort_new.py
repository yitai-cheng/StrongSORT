
import numpy as np
import torch

# from .deep.feature_extractor import Extractor, FastReIDExtractor
from deep_sort.deep.feature_extractor import Extractor
from deep_sort.sort.nn_matching import NearestNeighborDistanceMetric
from strongsort.deep_sort.detection import Detection
from strongsort.deep_sort.tracker import Tracker

__all__ = ["StrongSort"]


class StrongSort(object):
    def __init__(
        self,
        model_path,
        model_config=None,
        max_dist=0.2,
        min_confidence=0.3,
        nms_max_overlap=1.0,
        max_iou_distance=0.7,
        max_age=30,
        n_init=5,
        nn_budget=100,
        use_cuda=True,
    ):
        self.min_confidence = min_confidence
        self.nms_max_overlap = nms_max_overlap

        if model_config is None:
            self.extractor = Extractor(model_path, use_cuda=use_cuda)
        else:
            self.extractor = FastReIDExtractor(
                model_config, model_path, use_cuda=use_cuda
            )

        max_cosine_distance = max_dist
        metric = NearestNeighborDistanceMetric("cosine", max_cosine_distance, nn_budget)
        self.tracker = Tracker(
            metric, max_iou_distance=max_iou_distance, max_age=max_age, n_init=n_init
        )

    def update(
        self,
        bbox_xywh,
        classes,
        confidences,
        ori_img,
        prevent_different_classes_match=False,
        match_across_boundary=False,
    ):
        self.height, self.width = ori_img.shape[:2]
        # generate detections
        features = self._get_features(bbox_xywh, ori_img)
        bbox_tlwh = self._xywh_to_tlwh(bbox_xywh)
        detections = [
            Detection(bbox_tlwh[i], conf, features[i])
            for i, conf in enumerate(confidences)
            if conf > self.min_confidence
        ]

        # run on non-maximum suppression
        boxes = np.array([d.tlwh for d in detections])
        scores = np.array([d.confidence for d in detections])
        # classes = np.array([d.confidence for d in detections])
        indices = range(len(boxes))
        # indices = non_max_suppression(boxes, self.nms_max_overlap, scores)
        # print(indices)
        detections = [detections[i] for i in indices]

        # Update tracker.
        # if opt.ECC:
        #     tracker.camera_update(sequence_dir.split('/')[-1], frame_idx)

        # update tracker
        self.tracker.predict()
        self.tracker.update(
            detections,
            classes,
            scores,
            self.width,
            prevent_different_classes_match,
            match_across_boundary,
        )

        # output bbox identities
        outputs = []
        for track in self.tracker.tracks:
            if not track.is_confirmed() or track.time_since_update > 1:
                continue
            box = track.to_tlwh()
            if match_across_boundary:
                x1, y1, x2, y2 = self._tlwh_to_xyxy1(box)
            else:
                x1, y1, x2, y2 = self._tlwh_to_xyxy(box)
            track_id = track.track_id
            track_class = track._class
            track_score = track._score
            outputs.append(
                np.array(
                    [
                        int(x1),
                        int(y1),
                        int(x2),
                        int(y2),
                        int(track_class),
                        track_score,
                        int(track_id),
                    ]
                )
            )
        if len(outputs) > 0:
            outputs = np.stack(outputs, axis=0)
        return outputs

    """
    TODO:
        Convert bbox from xc_yc_w_h to xtl_ytl_w_h
    Thanks JieChen91@github.com for reporting this bug!
    """

    @staticmethod
    def _xywh_to_tlwh(bbox_xywh):
        if isinstance(bbox_xywh, np.ndarray):
            bbox_tlwh = bbox_xywh.copy()
        elif isinstance(bbox_xywh, torch.Tensor):
            bbox_tlwh = bbox_xywh.clone()

        try:
            bbox_tlwh[:, 0] = bbox_xywh[:, 0] - bbox_xywh[:, 2] / 2.0
            bbox_tlwh[:, 1] = bbox_xywh[:, 1] - bbox_xywh[:, 3] / 2.0
        except:
            bbox_tlwh = [[0, 0, 0, 0]]

        return bbox_tlwh

    def _xywh_to_xyxy(self, bbox_xywh):
        x, y, w, h = bbox_xywh
        x1 = max(int(x - w / 2), 0)
        x2 = min(int(x + w / 2), self.width - 1)
        y1 = max(int(y - h / 2), 0)
        y2 = min(int(y + h / 2), self.height - 1)
        return x1, y1, x2, y2

    def _tlwh_to_xyxy1(self, bbox_tlwh):
        """
        TODO:
            Convert bbox from xtl_ytl_w_h to xc_yc_w_h
        Thanks JieChen91@github.com for reporting this bug!
        """
        x, y, w, h = bbox_tlwh
        x1 = max(int(x), 0)
        x2 = int(x + w)
        y1 = max(int(y), 0)
        y2 = int(y + h)
        return x1, y1, x2, y2

    def _tlwh_to_xyxy(self, bbox_tlwh):
        """
        TODO:
            Convert bbox from xtl_ytl_w_h to xc_yc_w_h
        Thanks JieChen91@github.com for reporting this bug!
        """
        x, y, w, h = bbox_tlwh
        x1 = max(int(x), 0)
        x2 = min(int(x + w), self.width - 1)
        y1 = max(int(y), 0)
        y2 = min(int(y + h), self.height - 1)
        return x1, y1, x2, y2

    def _xyxy_to_tlwh(self, bbox_xyxy):
        x1, y1, x2, y2 = bbox_xyxy

        t = x1
        l = y1
        w = int(x2 - x1)
        h = int(y2 - y1)
        return t, l, w, h

    def _get_features(self, bbox_xywh, ori_img):
        im_crops = []
        for box in bbox_xywh:
            x1, y1, x2, y2 = self._xywh_to_xyxy(box)
            im = ori_img[y1:y2, x1:x2]
            im_crops.append(im)
        if im_crops:
            features = self.extractor(im_crops)
        else:
            features = np.array([])
        return features
