# -*- coding: utf-8 -*-
"""
Created on Wed Dec 21 19:00:00 2022

@author: Anna Grim
@email: anna.grim@alleninstitute.org

"""

import os
import numpy as np
from abc import ABC, abstractmethod
from eval.graph_routines import *
from eval.utils import *
from skimage.io import imread
from tifffile import imwrite

# define class variables: simple_width, complex_width, simple_color, complex_color

class SegmentationMetrics(ABC):

    def __init__(self, graphs, volume, shape, output, output_dir):
        """
        Constructs object which evaluates a segmentation mask in terms of the
        number of splits and merges.

        Parameters
        ----------
        graph : list[networkx.Graph()]
            List of graphs where each graph represents a neuron.
        volume : dict
            Sparse image volume of segmentation mask.
        shape : tuple
            Dimensions of "volume" in the order of (x,y,z).
        output : str
            Type of output.
        output_dir : str
            Directory where output is written to.

        Returns
        -------
        None.

        """
        assert output in [None, 'tif', 'swc']
        self.output = output
        self.output_dir = output_dir

        self.graphs = graphs
        self.volume = volume
        self.shape = shape
        if self.output in ['tif']:
            self.site_mask = np.zeros(self.shape, dtype=np.uint8)
            self.edge_mask = np.zeros(self.shape, dtype=np.uint8)

    def init_graphs(self, graphs_dir, path_to_volume):
        """
        Initializes a graph by either uploading swc files or dilating the graph.

        Parameters
        ----------
        graphs_dir : str
            Path to directory containing swc files.
        path_to_volume : str
            Path to image volume (i.e. tif file).

        Returns
        -------
        list[networkx.Graph()].
            List of graphs where each graph represents a neuron.

        """
        assert any([graphs_dir, path_to_volume])
        if graphs_dir != None:
            return swc_to_graph(graphs_dir, self.shape)
        else:
            volume = imread(path_to_volume)
            return volume_to_graph(volume)

    def init_volume(self, path_to_volume, graphs_dir):
        """
        Initializes a volume by either uploading a tif file or dilating its graph.

        Parameters
        ----------
        path_to_volume : str
            Path to image volume (i.e. tif file).
        graphs_dir : str
            Path to directory containing swc files.

        Returns
        -------
        dict
            Sparse image volume of segmentation mask.

        """
        assert any([path_to_volume, graphs_dir])
        if path_to_volume != None:
            if 'tif' in path_to_volume:
                volume = imread(path_to_volume)
                sparse_volume = volume_to_dict(volume)
                return sparse_volume
            elif 'goodgle' in path_to_volume:
                return upload_google_pred(path_to_volume)
        else:
            list_of_graphs = swc_to_graph(graphs_dir, self.shape)
            sparse_volume = graph_to_volume(list_of_graphs, self.shape)
            return sparse_volume

    def check_simple_mistake(self, a, b):
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
        return (a > 0 and b > 0) and (a != b)

    def check_complex_mistake(self, a, b):
        """
        Checks if one of "a" and "b" is positive and the other is zero-valued.

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
        condition_1 = (a > 0) and (b == 0)
        condition_2 = (b > 0) and (a == 0)
        return condition_1 or condition_2

    def log_simple_mistake(self, graph, i, fn):
        """
        Logs xyz coordinate of mistake in a numpy.array() or writes an swc file.

        Parameters
        ----------
        i : int
            Node of "graph".

        fn : str
            Filename of swc that will be written.

        Returns
        -------
        None

        """
        if self.output == 'swc':
            red = ' 1.0 0.0 0.0'
            xyz = get_xyz(graph, i)
            path_to_swc = os.path.join(self.output_dir, fn)
            write_swc(path_to_swc, [get_swc_entry(xyz, 7, -1)], color=red)
        elif self.output in ['tif']:
            idx = get_idx(graph, i)
            self.site_mask[idx] = 1

    def log_complex_mistake(self, graph, list_of_edges, root, fn):
        """
        Logs list of xyz coordinates of mistake in an numpyp.array() or writes
        an swc file.

        Parameters
        ----------
        list_of_edges : list[tuple]
            List of edges that form a path.
        root_edge : int
            Root node corresponding to "list_of_edges".
        fn: str
            Filename of swc that will be written.

        Returns
        -------
        None.

        """
        if self.output == 'swc':
            red = ' 1.0 0.0 0.0'
            reindex = {root: 1}
            swc = [get_swc_entry(get_xyz(graph, root), 7, -1)]
            for (i,j) in list_of_edges:
                xyz = get_xyz(graph, j)
                swc.append(get_swc_entry(xyz, 7, reindex[i]))
                reindex[j] = len(reindex) + 1
            path = os.path.join(self.output_dir, fn)
            write_swc(path, swc, color=red)
        elif self.output == 'tif':
            for (i,j) in list_of_edges:
                idx = get_idx(graph, j)
                self.edge_mask[idx] = 1
    
    def write_results(self, fn):
        """
        Writes "site_mask" and "edge" mask to 

        Parameters
        ----------
        fn : TYPE
            DESCRIPTION.

        Returns
        -------
        None.

        """
        if self.output in ['tif']:
            path_to_site_mask = os.path.join(self.output_dir, fn + 'sites.tif')
            path_to_edge_mask = os.path.join(self.output_dir, fn + 'edges.tif')
            imwrite(path_to_site_mask, self.site_mask)
            imwrite(path_to_edge_mask, self.edge_mask)

    @abstractmethod
    def detect_mistakes(self):
        pass

    @abstractmethod
    def compute_erl(self):
        pass

    @abstractmethod
    def process_complex_mistake(self):
        pass