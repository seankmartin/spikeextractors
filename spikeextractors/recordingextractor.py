from abc import ABC, abstractmethod
import numpy as np
import tempfile
import shutil
import random
from pathlib import Path
from .extraction_tools import load_probe_file, save_to_probe_file, write_to_binary_dat_format, \
    get_sub_extractors_by_property, cast_start_end_frame
from .baseextractor import BaseExtractor


class RecordingExtractor(ABC, BaseExtractor):
    '''A class that contains functions for extracting important information
    from recorded extracellular data. It is an abstract class so all
    functions with the @abstractmethod tag must be implemented for the
    initialization to work.
    '''
    def __init__(self):
        BaseExtractor.__init__(self)
        self._epochs = {}
        self._channel_properties = {}
        self.id = random.randint(a=0, b=9223372036854775807)

    def __del__(self):
        if self._tmp_folder is not None:
            try:
                shutil.rmtree(self._tmp_folder)
            except Exception as e:
                print('Impossible to delete temp file:', self._tmp_folder, 'Error', e)

    @abstractmethod
    def get_traces(self, channel_ids=None, start_frame=None, end_frame=None):
        '''This function extracts and returns a trace from the recorded data from the
        given channels ids and the given start and end frame. It will return
        traces from within three ranges:

            [start_frame, start_frame+1, ..., end_frame-1]
            [start_frame, start_frame+1, ..., final_recording_frame - 1]
            [0, 1, ..., end_frame-1]
            [0, 1, ..., final_recording_frame - 1]

        if both start_frame and end_frame are given, if only start_frame is
        given, if only end_frame is given, or if neither start_frame or end_frame
        are given, respectively. Traces are returned in a 2D array that
        contains all of the traces from each channel with dimensions
        (num_channels x num_frames). In this implementation, start_frame is inclusive
        and end_frame is exclusive conforming to numpy standards.

        Parameters
        ----------
        start_frame: int
            The starting frame of the trace to be returned (inclusive)
        end_frame: int
            The ending frame of the trace to be returned (exclusive)
        channel_ids: array_like
            A list or 1D array of channel ids (ints) from which each trace will be
            extracted

        Returns
        ----------
        traces: numpy.ndarray
            A 2D array that contains all of the traces from each channel.
            Dimensions are: (num_channels x num_frames)
        '''
        pass

    @abstractmethod
    def get_num_frames(self):
        '''This function returns the number of frames in the recording

        Returns
        -------
        num_frames: int
            Number of frames in the recording (duration of recording)
        '''
        pass

    @abstractmethod
    def get_sampling_frequency(self):
        '''This function returns the sampling frequency in units of Hz.

        Returns
        -------
        fs: float
            Sampling frequency of the recordings in Hz
        '''
        pass

    @abstractmethod
    def get_channel_ids(self):
        '''Returns the list of channel ids. If not specified, the range from 0 to num_channels - 1 is returned.

        Returns
        -------
        channel_ids: list
            Channel list

        '''
        pass

    def get_num_channels(self):
        '''This function returns the number of channels in the recording.

        Returns
        -------
        num_channels: int
            Number of channels in the recording
        '''
        # print('WARNING: this is a temporary warning. You should use get_channel_ids() to iterate through the channels. '
        #       'This warning will be removed in future versions of SpikeInterface.')
        return len(self.get_channel_ids())

    def get_dtype(self):
        return self.get_traces(channel_ids=[self.get_channel_ids()[0]], start_frame=0, end_frame=1).dtype

    def frame_to_time(self, frame):
        '''This function converts a user-inputted frame index to a time with units of seconds.

        Parameters
        ----------
        frame: float
            The frame to be converted to a time

        Returns
        -------
        time: float
            The corresponding time in seconds
        '''
        # Default implementation
        return frame / self.get_sampling_frequency()

    def time_to_frame(self, time):
        '''This function converts a user-inputted time (in seconds) to a frame index.

        Parameters
        -------
        time: float
            The time (in seconds) to be converted to frame index

        Returns
        -------
        frame: float
            The corresponding frame index
        '''
        # Default implementation
        return time * self.get_sampling_frequency()

    def get_snippets(self, reference_frames, snippet_len, channel_ids=None):
        '''This function returns data snippets from the given channels that
        are starting on the given frames and are the length of the given snippet
        lengths before and after.

        Parameters
        ----------
        snippet_len: int or tuple
            If int, the snippet will be centered at the reference frame and
            and return half before and half after of the length. If tuple,
            it will return the first value of before frames and the second value
            of after frames around the reference frame (allows for asymmetry)
        reference_frames: array_like
            A list or array of frames that will be used as the reference frame of
            each snippet
        channel_ids: array_like
            A list or array of channel ids (ints) from which each trace will be
            extracted

        Returns
        ----------
        snippets: numpy.ndarray
            Returns a list of the snippets as numpy arrays.
            The length of the list is len(reference_frames)
            Each array has dimensions: (num_channels x snippet_len)
            Out-of-bounds cases should be handled by filling in zeros in the snippet
        '''
        # Default implementation
        if isinstance(snippet_len, (tuple, list, np.ndarray)):
            snippet_len_before = snippet_len[0]
            snippet_len_after = snippet_len[1]
        else:
            snippet_len_before = int((snippet_len + 1) / 2)
            snippet_len_after = snippet_len - snippet_len_before

        if channel_ids is None:
            channel_ids = self.get_channel_ids()

        num_snippets = len(reference_frames)
        num_channels = len(channel_ids)
        num_frames = self.get_num_frames()
        snippet_len_total = int(snippet_len_before + snippet_len_after)
        snippets = np.zeros((num_snippets, num_channels, snippet_len_total))

        for i in range(num_snippets):
            snippet_chunk = np.zeros((num_channels, snippet_len_total))
            if 0 <= reference_frames[i] < num_frames:
                snippet_range = np.array(
                    [int(reference_frames[i]) - snippet_len_before, int(reference_frames[i]) + snippet_len_after])
                snippet_buffer = np.array([0, snippet_len_total])
                # The following handles the out-of-bounds cases
                if snippet_range[0] < 0:
                    snippet_buffer[0] -= snippet_range[0]
                    snippet_range[0] -= snippet_range[0]
                if snippet_range[1] >= num_frames:
                    snippet_buffer[1] -= snippet_range[1] - num_frames
                    snippet_range[1] -= snippet_range[1] - num_frames
                snippet_chunk[:, snippet_buffer[0]:snippet_buffer[1]] = self.get_traces(channel_ids=channel_ids,
                                                                                        start_frame=snippet_range[0],
                                                                                        end_frame=snippet_range[1])
            snippets[i] = snippet_chunk
        return snippets

    def set_channel_locations(self, locations, channel_ids=None):
        '''This function sets the location properties of each specified channel
        id with the corresponding locations of the passed in locations list.

        Parameters
        ----------
        channel_ids: array_like
            The channel ids (ints) for which the locations will be specified
        locations: array_like
            A list of corresponding locations (array_like) for the given channel_ids
        '''
        if channel_ids is None:
            channel_ids = self.get_channel_ids()
        if len(channel_ids) == len(locations):
            for i in range(len(channel_ids)):
                if isinstance(locations[i], (list, np.ndarray)):
                    location = np.asarray(locations[i])
                    self.set_channel_property(channel_ids[i], 'location', location.astype(float))
                else:
                    raise TypeError(str(locations[i]) + " must be an array_like")
        else:
            raise ValueError("channel_ids and locations must have same length")

    def get_channel_locations(self, channel_ids=None):
        '''This function returns the location of each channel specifed by
        channel_ids

        Parameters
        ----------
        channel_ids: array_like
            The channel ids (ints) for which the locations will be returned

        Returns
        ----------
        locations: array_like
            Returns a list of corresonding locations (floats) for the given
            channel_ids
        '''
        if channel_ids is None:
            channel_ids = self.get_channel_ids()
        locations = []
        for channel_id in channel_ids:
            location = self.get_channel_property(channel_id, 'location')
            locations.append(location)
        return np.array(locations)

    def set_channel_groups(self, groups, channel_ids=None):
        '''This function sets the group property of each specified channel
        id with the corresponding group of the passed in groups list.

        Parameters
        ----------
        groups: array_like
            A list of groups (ints) for the channel_ids
        channel_ids: array_like or None
            The channel ids (ints) for which the groups will be specified. If None, all channel ids are assumed
        '''
        if channel_ids is None:
            channel_ids = self.get_channel_ids()
        if len(channel_ids) == len(groups):
            for i in range(len(channel_ids)):
                if isinstance(groups[i], (int, np.integer)):
                    self.set_channel_property(channel_ids[i], 'group', groups[i])
                else:
                    raise TypeError(str(groups[i]) + " must be an int")
        else:
            raise ValueError("channel_ids and groups must have same length")

    def get_channel_groups(self, channel_ids=None):
        '''This function returns the group of each channel specifed by
        channel_ids

        Parameters
        ----------
        channel_ids: array_like
            The channel ids (ints) for which the groups will be returned

        Returns
        ----------
        groups: array_like
            Returns a list of corresonding groups (ints) for the given
            channel_ids
        '''
        if channel_ids is None:
            channel_ids = self.get_channel_ids()
        groups = []
        for channel_id in channel_ids:
            group = self.get_channel_property(channel_id, 'group')
            groups.append(group)
        return groups

    def set_channel_gains(self, channel_ids, gains):
        '''This function sets the gain property of each specified channel
        id with the corresponding group of the passed in gains float/list.

        Parameters
        ----------
        channel_ids: array_like
            The channel ids (ints) for which the groups will be specified
        gains: float/array_like
            If a float, each channel will be assigned the corresponding gain.
            If a list, each channel will be given a gain from the list
        '''
        if isinstance(gains, (int, np.integer, float, np.float64)):
            gain = float(gains)
            for i in range(len(channel_ids)):
                self.set_channel_property(channel_ids[i], 'gain', gain)
        elif isinstance(gains, (list, np.ndarray)):
            if len(channel_ids) == len(gains):
                for i in range(len(channel_ids)):
                    if isinstance(gains[i], (int, np.integer, float, np.float64)):
                        self.set_channel_property(channel_ids[i], 'gain', float(gains[i]))
                    else:
                        raise TypeError("all gains must be floats or ints")
            else:
                raise ValueError("channel_ids and gains must have same length")
        else:
            raise TypeError("gains must be a int/float or a list of int/floats")

    def get_channel_gains(self, channel_ids=None):
        '''This function returns the gain of each channel specifed by
        channel_ids.

        Parameters
        ----------
        channel_ids: array_like
            The channel ids (ints) for which the gains will be returned

        Returns
        ----------
        gains: array_like
            Returns a list of corresonding gains (floats) for the given
            channel_ids
        '''
        if channel_ids is None:
            channel_ids = self.get_channel_ids()
        gains = []
        for channel_id in channel_ids:
            gain = self.get_channel_property(channel_id, 'gain')
            gains.append(gain)
        return gains

    def set_channel_property(self, channel_id, property_name, value):
        '''This function adds a property dataset to the given channel under the
        property name.

        Parameters
        ----------
        channel_id: int
            The channel id for which the property will be added
        property_name: str
            A property stored by the RecordingExtractor (location, etc.)
        value:
            The data associated with the given property name. Could be many
            formats as specified by the user
        '''
        if isinstance(channel_id, (int, np.integer)):
            if channel_id in self.get_channel_ids():
                if channel_id not in self._channel_properties:
                    self._channel_properties[channel_id] = {}
                if isinstance(property_name, str):
                    self._channel_properties[channel_id][property_name] = value
                else:
                    raise TypeError(str(property_name) + " must be a string")
            else:
                raise ValueError(str(channel_id) + " is not a valid channel_id")
        else:
            raise TypeError(str(channel_id) + " must be an int")

    def get_channel_property(self, channel_id, property_name):
        '''This function returns the data stored under the property name from
        the given channel.

        Parameters
        ----------
        channel_id: int
            The channel id for which the property will be returned
        property_name: str
            A property stored by the RecordingExtractor (location, etc.)

        Returns
        ----------
        property_data
            The data associated with the given property name. Could be many
            formats as specified by the user
        '''
        if not isinstance(channel_id, (int, np.integer)):
            raise TypeError(str(channel_id) + " must be an int")
        if channel_id not in self.get_channel_ids():
            raise ValueError(str(channel_id) + " is not a valid channel_id")
        if channel_id not in self._channel_properties:
            raise ValueError('no properties found for channel' + str(channel_id))
        if property_name not in self._channel_properties[channel_id]:
            raise RuntimeError(str(property_name) + " has not been added to channel " + str(channel_id))
        if not isinstance(property_name, str):
            raise TypeError(str(property_name) + " must be a string")
        return self._channel_properties[channel_id][property_name]

    def get_channel_property_names(self, channel_id):
        '''Get a list of property names for a given channel.
         Parameters
        ----------
        channel_id: int
            The channel id for which the property names will be returned
            If None (default), will return property names for all channels
        Returns
        ----------
        property_names
            The list of property names
        '''
        if isinstance(channel_id, (int, np.integer)):
            if channel_id in self.get_channel_ids():
                if channel_id not in self._channel_properties:
                    self._channel_properties[channel_id] = {}
                property_names = sorted(self._channel_properties[channel_id].keys())
                return property_names
            else:
                raise ValueError(str(channel_id) + " is not a valid channel_id")
        else:
            raise TypeError(str(channel_id) + " must be an int")

    def get_shared_channel_property_names(self, channel_ids=None):
        '''Get the intersection of channel property names for a given set of channels or for all channels if channel_ids is None.
         Parameters
        ----------
        channel_ids: array_like
            The channel ids for which the shared property names will be returned.
            If None (default), will return shared property names for all channels
        Returns
        ----------
        property_names
            The list of shared property names
        '''
        if channel_ids is None:
            channel_ids = self.get_channel_ids()
        property_names = []
        curr_property_name_set = set(self.get_channel_property_names(channel_id=channel_ids[0]))
        for channel_id in channel_ids[1:]:
            curr_channel_property_name_set = set(self.get_channel_property_names(channel_id=channel_id))
            curr_property_name_set = curr_property_name_set.intersection(curr_channel_property_name_set)
        property_names = sorted(list(curr_property_name_set))
        return property_names

    def copy_channel_properties(self, recording, channel_ids=None):
        '''Copy channel properties from another recording extractor to the current
        recording extractor.

        Parameters
        ----------
        recording: RecordingExtractor
            The recording extractor from which the properties will be copied
        channel_ids: (array_like, int)
            The list (or single value) of channel_ids for which the properties will be copied
        '''
        if channel_ids is None:
            channel_ids = recording.get_channel_ids()
        if isinstance(channel_ids, int):
            curr_property_names = recording.get_channel_property_names(channel_id=channel_ids)
            for curr_property_name in curr_property_names:
                value = recording.get_channel_property(channel_id=channel_ids, property_name=curr_property_name)
                self.set_channel_property(channel_id=channel_ids, property_name=curr_property_name, value=value)
        else:
            for channel_id in channel_ids:
                curr_property_names = recording.get_channel_property_names(channel_id=channel_id)
                for curr_property_name in curr_property_names:
                    value = recording.get_channel_property(channel_id=channel_id, property_name=curr_property_name)
                    self.set_channel_property(channel_id=channel_id, property_name=curr_property_name, value=value)
    
    def clear_channel_property(self, channel_id, property_name):
        '''This function clears the channel property for the given property.

        Parameters
        ----------
        channel_id: int
            The id that specifies a channel in the recording
        property_name: string
            The name of the property to be cleared
        '''
        if channel_id in self._channel_properties:
            if property_name in self._channel_properties[channel_id]:
                del self._channel_properties[channel_id][property_name]

    def clear_channels_property(self, property_name, channel_ids=None):
        '''This function clears the channels' properties for the given property.

        Parameters
        ----------
        property_name: string
            The name of the property to be cleared
        channel_ids: list
            A list of ids that specifies a set of channels in the recording. If None all channels ar cleared
        '''
        if channel_ids is None:
            channel_ids = self.get_channel_ids()
        for channel_id in channel_ids:
            self.clear_channel_property(channel_id, property_name)
            
    def add_epoch(self, epoch_name, start_frame, end_frame):
        '''This function adds an epoch to your recording extractor that tracks
        a certain time period in your recording. It is stored in an internal
        dictionary of start and end frame tuples.

        Parameters
        ----------
        epoch_name: str
            The name of the epoch to be added
        start_frame: int
            The start frame of the epoch to be added (inclusive)
        end_frame: int
            The end frame of the epoch to be added (exclusive). If set to None, it will include the entire
            recording after the start_frame
        '''
        if isinstance(epoch_name, str):
            start_frame, end_frame = cast_start_end_frame(start_frame, end_frame)
            self._epochs[epoch_name] = {'start_frame': start_frame, 'end_frame': end_frame}
        else:
            raise TypeError("epoch_name must be a string")

    def remove_epoch(self, epoch_name):
        '''This function removes an epoch from your recording extractor.

        Parameters
        ----------
        epoch_name: str
            The name of the epoch to be removed
        '''
        if isinstance(epoch_name, str):
            if epoch_name in list(self._epochs.keys()):
                del self._epochs[epoch_name]
            else:
                raise RuntimeError("This epoch has not been added")
        else:
            raise TypeError("epoch_name must be a string")

    def get_epoch_names(self):
        '''This function returns a list of all the epoch names in your recording

        Returns
        ----------
        epoch_names: list
            List of epoch names in the recording extractor
        '''
        epoch_names = list(self._epochs.keys())
        if not epoch_names:
            pass
        else:
            epoch_start_frames = []
            for epoch_name in epoch_names:
                epoch_info = self.get_epoch_info(epoch_name)
                start_frame = epoch_info['start_frame']
                epoch_start_frames.append(start_frame)
            epoch_names = [epoch_name for _, epoch_name in sorted(zip(epoch_start_frames, epoch_names))]
        return epoch_names

    def get_epoch_info(self, epoch_name):
        '''This function returns the start frame and end frame of the epoch
        in a dict.

        Parameters
        ----------
        epoch_name: str
            The name of the epoch to be returned

        Returns
        ----------
        epoch_info: dict
            A dict containing the start frame and end frame of the epoch
        '''
        # Default (Can add more information into each epoch in subclass)
        if isinstance(epoch_name, str):
            if epoch_name in list(self._epochs.keys()):
                epoch_info = self._epochs[epoch_name]
                return epoch_info
            else:
                raise RuntimeError("This epoch has not been added")
        else:
            raise TypeError("epoch_name must be a string")

    def get_epoch(self, epoch_name):
        '''This function returns a SubRecordingExtractor which is a view to the
        given epoch

        Parameters
        ----------
        epoch_name: str
            The name of the epoch to be returned

        Returns
        ----------
        epoch_extractor: SubRecordingExtractor
            A SubRecordingExtractor which is a view to the given epoch
        '''
        epoch_info = self.get_epoch_info(epoch_name)
        start_frame = epoch_info['start_frame']
        end_frame = epoch_info['end_frame']
        from .subrecordingextractor import SubRecordingExtractor
        return SubRecordingExtractor(parent_recording=self, start_frame=start_frame,
                                     end_frame=end_frame)

    def load_probe_file(self, probe_file, channel_map=None, channel_groups=None, verbose=False):
        '''This function returns a SubRecordingExtractor that contains information from the given
        probe file (channel locations, groups, etc.) If a .prb file is given, then 'location' and 'group' 
        information for each channel is added to the SubRecordingExtractor. If a .csv file is given, then 
        it will only add 'location' to the SubRecordingExtractor.

        Parameters
        ----------
        recording: RecordingExtractor
            The recording extractor to channel information
        probe_file: str
            Path to probe file. Either .prb or .csv
        verbose: bool
            If True, output is verbose

        Returns
        ---------
        subrecording = SubRecordingExtractor
            The extractor containing all of the probe information.
        '''
        subrecording = load_probe_file(self, probe_file, channel_map=channel_map, 
                                       channel_groups=channel_groups, verbose=verbose)
        return subrecording

    def save_to_probe_file(self, probe_file, grouping_property=None, radius=None,
                           graph=True, geometry=True, verbose=False):
        '''Saves probe file from the channel information of this recording extractor.

        Parameters
        ----------
        probe_file: str
            file name of .prb or .csv file to save probe information to
        grouping_property: str (default None)
            If grouping_property is a shared_channel_property, different groups are saved based on the property.
        radius: float (default None)
            Adjacency radius (used by some sorters). If None it is not saved to the probe file.
        graph: bool
            If True, the adjacency graph is saved (default=True)
        geometry: bool
            If True, the geometry is saved (default=True)
        verbose: bool
            If True, output is verbose
        '''
        save_to_probe_file(self, probe_file, grouping_property=grouping_property, radius=radius,
                           graph=graph, geometry=geometry, verbose=verbose)

    def write_to_binary_dat_format(self, save_path, time_axis=0, dtype=None, chunk_size=None, chunk_mb=500):
        '''Saves the traces of this recording extractor into binary .dat format.

        Parameters
        ----------
        save_path: str
            The path to the file.
        time_axis: 0 (default) or 1
            If 0 then traces are transposed to ensure (nb_sample, nb_channel) in the file.
            If 1, the traces shape (nb_channel, nb_sample) is kept in the file.
        dtype: dtype
            Type of the saved data. Default float32
        chunk_size: None or int
            If not None then the file is saved in chunks.
            This avoid to much memory consumption for big files.
            If 'auto' the file is saved in chunks of ~ 500Mb
        chunk_mb: None or int
            Chunk size in Mb (default 500Mb)
        '''
        write_to_binary_dat_format(self, save_path=save_path, time_axis=time_axis, dtype=dtype, chunk_size=chunk_size,
                                   chunk_mb=chunk_mb)
   
    def get_sub_extractors_by_property(self, property_name, return_property_list=False):
        '''Returns a list of SubRecordingExtractors from this RecordingExtractor based on the given
        property_name (e.g. group)

        Parameters
        ----------
        property_name: str
            The property used to subdivide the extractor
        return_property_list: bool
            If True the property list is returned

        Returns
        -------
        sub_list: list
            The list of subextractors to be returned
        OR
        sub_list, prop_list
            If return_property_list is True, the property list will be returned as well

        '''
        if return_property_list:
            sub_list, prop_list = get_sub_extractors_by_property(self, property_name=property_name, 
                                                                 return_property_list=return_property_list)
            return sub_list, prop_list
        else:
            sub_list = get_sub_extractors_by_property(self, property_name=property_name, 
                                                      return_property_list=return_property_list)
            return sub_list

    @staticmethod
    def write_recording(recording, save_path):
        '''This function writes out the recorded file of a given recording
        extractor to the file format of this current recording extractor. Allows
        for easy conversion between recording file formats. It is a static
        method so it can be used without instantiating this recording extractor.

        Parameters
        ----------
        recording: RecordingExtractor
            An RecordingExtractor that can extract information from the recording
            file to be converted to the new format.

        save_path: string
            A path to where the converted recorded data will be saved, which may
            either be a file or a folder, depending on the format.
        '''
        raise NotImplementedError("The write_recording function is not \
                                  implemented for this extractor")
