# -*- coding: utf-8 -*-
"""
Created on Wed Dec 21 19:00:00 2022

@author: Anna Grim
@email: anna.grim@alleninstitute.org

"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import time

import networkx as nx
import tensorstore as ts
from toolbox.utils import progress_bar

from segmentation_skeleton_metrics import graph_utils as gutils
from segmentation_skeleton_metrics import utils
from segmentation_skeleton_metrics.swc_utils import to_graph


class SkeletonMetric:
    """
    Class that evaluates a segmentation in terms of the number of
    splits and merges.

    """

    def __init__(
        self,
        swc_paths,
        labels,
        anisotropy=[1.0, 1.0, 1.0],
        equivalent_ids=None,
        valid_ids=None,
    ):
        """
        Constructs object that evaluates a predicted segmentation.

        Parameters
        ----------
        ...

        Returns
        -------
        None.

        """
        self.valid_ids = valid_ids
        self.labels = labels
        self.target_graphs = self.init_target_graphs(swc_paths, anisotropy)
        self.pred_graphs = self.init_pred_graphs()

    def init_target_graphs(self, paths, anisotropy):
        target_graphs = dict()
        for path in paths:
            swc_id = os.path.basename(path).replace(".swc", "")
            target_graphs[swc_id] = to_graph(path, anisotropy=anisotropy)
        return target_graphs

    def init_pred_graphs(self):
        print("Labelling Target Graphs...")
        t0 = time()
        pred_graphs = dict()
        for cnt, (swc_id, graph) in enumerate(self.target_graphs.items()):
            progress_bar(cnt + 1, len(self.target_graphs))
            pred_graphs[swc_id] = self.label_graph(graph)
        t, unit = utils.time_writer(time() - t0)
        print(f"\nRuntime: {round(t, 2)} {unit}\n")
        return pred_graphs

    def label_graph(self, target_graph):
        pred_graph = gutils.empty_copy(target_graph)
        with ThreadPoolExecutor() as executor:
            # Assign threads
            threads = []
            for i in pred_graph.nodes:
                img_coord = gutils.get_coord(target_graph, i)
                threads.append(executor.submit(self.get_label, img_coord, i))
            # Store results
            for thread in as_completed(threads):
                i, label = thread.result()
                pred_graph.nodes[i].update({"pred_id": label})
        return pred_graph

    def get_label(self, img_coord, return_node=False):
        """
        Gets label of voxel at "img_coord".

        Parameters
        ----------
        img_coord : numpy.ndarray
            Image coordinate of voxel to be read.

        Returns
        -------
        int
           Label of voxel at "img_coord".

        """
        label = self.__read_label(img_coord)
        if return_node:
            return return_node, self.validate_label(label)
        else:
            return self.validate_label(label)

    def __read_label(self, xyz):
        """
        Gets label at image coordinates "xyz".

        Parameters
        ----------
        xyz : tuple[int]
            Coordinates that index into "self.labels".

        Returns
        -------
        int
           Label at image coordinates "xyz".

        """
        if type(self.labels) == ts.TensorStore:
            return int(self.labels[xyz].read().result())
        else:
            return self.labels[xyz]

    def validate_label(self, label):
        """
        Validates label by checking whether it is contained in
        "self.valid_ids".

        Parameters
        ----------
        label : int
            Label to be validated.

        Returns
        -------
        label : int
            There are two possibilities: (1) original label if either "label"
            is contained in "self.valid_ids" or "self.valid_labels" is None,
            or (2) 0 if "label" is not contained in self.valid_ids.

        """
        if self.valid_ids:
            if label not in self.valid_ids:
                return 0
        return label

    def compute_metrics(self):
        """
        Computes skeleton-based metrics.

        Parameters
        ----------
        None

        Returns
        -------
        ...

        """
        self.detect_splits()
        pass

    def detect_splits(self):
        """
        Detects splits in the predicted segmentation.

        Parameters
        ----------
        None

        Returns
        -------
        None

        """
        print("Detecting Splits...")
        t0 = time()
        target_graphs = self.target_graphs.items()
        for cnt, (swc_id, target_graph) in enumerate(target_graphs):
            # Initializations
            progress_bar(cnt + 1, len(self.target_graphs))
            pred_graph = self.pred_graphs[swc_id]

            # Run dfs
            r = gutils.sample_leaf(target_graph)
            dfs_edges = list(nx.dfs_edges(target_graph, source=r))
            while len(dfs_edges) > 0:
                # Visit edge
                (i, j) = dfs_edges.pop(0)
                label_i = pred_graph.nodes[i]["pred_id"]
                label_j = pred_graph.nodes[j]["pred_id"]
                if self.is_split(label_i, label_j):
                    pred_graph = gutils.remove_edge(pred_graph, i, j)
                elif label_j == 0:
                    dfs_edges, pred_graph = self.split_search(
                        target_graph, pred_graph, dfs_edges, i, j
                    )

            # Update predicted graph
            self.pred_graphs[swc_id] = edit_graph(pred_graph)

        # Report runtime
        t, unit = utils.time_writer(time() - t0)
        print(f"\nRuntime: {round(t, 2)} {unit}\n")

    def is_split(self, a, b):
        """
        Checks if "a" and "b" are positive and not equal.

        Parameters
        ----------
        a : int
            label at node i.
        b : int
            label at node j.

        Returns
        -------
        bool
            Indicates whether there is a mistake.

        """
        if self.valid_ids is not None:
            if a not in self.valid_ids or b not in self.valid_ids:
                return False
        return (a != 0 and b != 0) and (a != b)

    def split_search(self, target_graph, pred_graph, dfs_edges, nb, root):
        """
        Determines whether zero-valued corresponds to a split or misalignment
        between "target_graph" and the predicted segmentation mask.

        Parameters
        ----------
        target_graph : networkx.Graph
            ...
        pred_graph : networkx.Graph
            ...
        dfs_edges : list[tuple]
            List of edges to be processed for split detection.
        nb : int
            Neighbor of "root".
        root : int
            Node where possible split starts (i.e. zero-valued label).

        Returns
        -------
        dfs_edges : list[tuple].
            Updated "dfs_edges" with visited edges removed.
        pred_graph : networkx.Graph
            ...

        """
        # Search
        queue = [root]
        visited = set()
        collision_labels = set()
        collision_nodes = set()
        while len(queue) > 0:
            j = queue.pop(0)
            label_j = pred_graph.nodes[j]["pred_id"]
            visited.add(j)
            if label_j != 0:
                collision_labels.add(label_j)
            else:
                nbs = target_graph.neighbors(j)
                for k in [k for k in nbs if k not in visited]:
                    if utils.check_edge(dfs_edges, (j, k)):
                        queue.append(k)
                        dfs_edges = remove_edge(dfs_edges, (j, k))
                    elif k == nb:
                        queue.append(k)

        # Upd zero nodes
        if len(collision_labels) == 1:
            label = collision_labels.pop()
            visited = visited.difference(collision_nodes)
            pred_graph = upd_nodes(pred_graph, visited, label)

        return dfs_edges, pred_graph


# -- utils --
def upd_nodes(graph, nodes, label):
    for i in nodes:
        graph.nodes[i].update({"pred_id": label})
    return graph


def edit_graph(graph):
    delete_nodes = []
    for i in graph.nodes:
        label = graph.nodes[i]["pred_id"]
        if label == 0:
            delete_nodes.append(i)
        else:
            graph.graph["pred_ids"].add(label)
    graph.remove_nodes_from(delete_nodes)
    return graph


def remove_edge(dfs_edges, edge):
    """
    Checks whether "edge" is in "dfs_edges" and removes it.

    Parameters
    ----------
    dfs_edges : list or set
        List or set of edges.
    edge : tuple
        Edge.

    Returns
    -------
    edges : list or set
        Updated list or set of edges with "dfs_edges" removed if it was contained
        in "dfs_edges".

    """
    if edge in dfs_edges:
        dfs_edges.remove(edge)
    elif (edge[1], edge[0]) in dfs_edges:
        dfs_edges.remove((edge[1], edge[0]))
    return dfs_edges
