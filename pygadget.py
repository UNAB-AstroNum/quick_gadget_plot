# Author: Lucas A. Bignone
# Contact: lbignone@iafe.uba.ar

from struct import unpack
from numpy import fromstring, fromfile, concatenate, array
from numpy import sqrt, searchsorted, unique
import pandas as pd
from functools import wraps
# from astropy.utils.console import ProgressBar

from astropy import units as u

from copy import copy

import numpy as np

## This private helper function returns the age of a star (in yr) given the universe expansion factor
# when the star was born (in range 0-1)
def age(R):
    H0 = 2.3e-18
    OmegaM0 = 0.27
    yr = 365.25 * 24 * 3600
    T0 = 13.7e9
    return T0 - (2./3./H0/np.sqrt(1-OmegaM0)) * np.arcsinh(np.sqrt( (1/OmegaM0-1)*R**3 ))/ yr


particle_keys = [
    "gas",
    "halo",
    "disk",
    "bulge",
    "stars",
    "bndry",
]

element_keys = [
    "He",
    "C",
    "Mg",
    "O",
    "Fe",
    "Si",
    "H",
    "N",
    "Ne",
    "S",
    "Ca",
    "Zi",
]


def memoize(func):
    """Memoization decorator"""
    cache = {}

    @wraps(func)
    def wrap(*args):
        if args not in cache:
            cache[args] = func(*args)
        return cache[args]
    return wrap


class Simulation:

    """ Base class for  handling GADGET3 snapshots

    Attributes:
        name (str):    File name of the snapshot.
        flags (dict):   Flags to signal presence of certain special blocks.
        particle_keys (list of str):    Names of particle types.
        block_keys (list of str):   Names of block types.
        element_keys (list of str): Names of chemical elements.
        particle_numbers (dict):    Particle numbers of each type.
        mass_number (dict): Particle masses of each type. If 0 for a type
            which is present, individual particles masses are stored in the
            mass block.
        cosmic_time (float):    Time of output, or expansion factor for
            cosmological simulations.
        redshift (float):   redshift
        omega_matter (float):   Matter density at redshift zero in units
            of critical density.
        omega_lambda (float):   Cosmological energy density at redshift
            zero in units of critical density.
        h (float):  Hubble parameter
        particle_total_numbers (dict):  Total number of particles of each
            type
        particle_total_numbers_hw (dict):   Most significant word of 64-bit
            total particle numbers for simulations with more than 2e32
            particles. Otherwise zero.
        swap (char):    Endianness represented by a single character
            ('<': little-endian, '>': big-endian).
    """

    def __init__(self, name, pot=False, accel=False, endt=False, tstp=False,
                 multiple_files=False, skip_file_check=False,
                 use_longids=False):
        """'Simulation' initialization

        Args:
            name (str): Snapshot filename (full path).

            pot (bool): Flag to signal presence of gravitational potential
                block. Defaults to False.
            accel (bool):   Flag to signal presence of acceleration block.
                Defaults to False.
            endt (bool):    Flag to signal presence of rate of change of
                entropic function block. Defaults to False.
            tstp (bool):    Flag to signal presence of timesteps block.
                Defaults to False.
        """

        # self.cache = {}

        self.basename = name
        self.name = name
        self.multiple_files = multiple_files
        self.use_longids = use_longids

        if self.multiple_files:
            self.name = self.basename+".0"

        self.flags = {}
        self.flags["pot"] = pot
        self.flags["accel"] = accel
        self.flags["endt"] = endt
        self.flags["tstp"] = tstp

        self.particle_keys = [
            "gas",
            "halo",
            "disk",
            "bulge",
            "stars",
            "bndry",
        ]

        self.block_keys = [
            "header",
            "pos",
            "vel",
            "id",
            "mass",
            "u",
            "rho",
            "ne",
            "nh",
            "hsml",
            "sfr",
            "age",
            "metals",
            "pot",
            "accel",
            "endt",
            "tstp",
            "esn",
            "esncold",
        ]

        self.element_keys = [
            "He",
            "C",
            "Mg",
            "O",
            "Fe",
            "Si",
            "H",
            "N",
            "Ne",
            "S",
            "Ca",
            "Zi",
        ]

        self._read_header()
        if not skip_file_check:
            self._file_check()
        self.set_units()

    def _read_header(self):
        """Read snapshot header information and check for file endianness

        Raises:
            NameError:  If block limits do not not match expected size.
        """

        f = open(self.name, 'rb')

        size_swaped = 65536
        size_checked = 256
        size_used = 196
        size_unused = size_checked - size_used

        data = f.read(4)
        size = unpack('i', data)[0]

        if (size == size_swaped):
            self.swap = '>'
        elif (size == size_checked):
            self.swap = '<'
        else:
            raise NameError("Error reading header in file: %s" % self.name)

        s = self.swap

        self.particle_numbers = {}
        for key in self.particle_keys:
            data = f.read(4)
            self.particle_numbers[key] = unpack(s+'I', data)[0]

        self.particle_mass = {}
        for key in self.particle_keys:
            data = f.read(8)
            self.particle_mass[key] = unpack(s+'d', data)[0]

        data = f.read(8)
        self.cosmic_time = unpack(s+'d', data)[0]

        data = f.read(8)
        self.redshift = unpack(s+'d', data)[0]

        data = f.read(4)
        self.flags["sfr"] = unpack(s+'i', data)[0]

        data = f.read(4)
        self.flags["feedback"] = unpack(s+'i', data)[0]

        self.particle_total_numbers = {}
        for key in self.particle_keys:
            data = f.read(4)
            self.particle_total_numbers[key] = unpack(s+'I', data)[0]

        data = f.read(4)
        self.flags["cooling"] = unpack(s+'i', data)[0]

        data = f.read(4)
        self.file_number = unpack(s+'i', data)[0]

        data = f.read(8)
        self.box_size = unpack(s+'d', data)[0]

        data = f.read(8)
        self.omega_matter = unpack(s+'d', data)[0]

        data = f.read(8)
        self.omega_lambda = unpack(s+'d', data)[0]

        data = f.read(8)
        self.h = unpack(s+'d', data)[0]

        data = f.read(4)
        self.flags["stellar_age"] = unpack(s+'i', data)[0]

        data = f.read(4)
        self.flags["metals"] = unpack(s+'i', data)[0]

        self.particle_total_numbers_hw = {}
        for key in self.particle_keys:
            data = f.read(4)
            self.particle_total_numbers_hw[key] = unpack(s+'i', data)[0]

        data = f.read(4)
        self.flags["entr_ics"] = unpack(s+'i', data)[0]

        f.read(size_unused)
        data = f.read(4)
        size = unpack(s+'i', data)[0]

        if (size != size_checked):
            raise NameError("Error reading header in file: %s" % self.name)

        f.close()

        self._file_structure()

    def _file_structure(self):
        """Compute block sizes."""

        total_number = 0
        mass_number = 0
        for key in self.particle_keys:
            number = self.particle_numbers[key]
            total_number += number
            if (number != 0 and self.particle_mass[key] == 0):
                mass_number += number

        data_size = 4
        dims = 3
        metals = len(self.element_keys)

        size = total_number * data_size
        size_space = size * dims
        size_mass = mass_number * data_size
        size_gas = self.particle_numbers["gas"] * data_size
        size_stars = self.particle_numbers["stars"] * data_size
        size_baryons = size_gas + size_stars
        size_metals = size_baryons * metals

        self.block_sizes = {}
        self.block_sizes["header"] = 256
        self.block_sizes["pos"] = size_space
        self.block_sizes["vel"] = size_space
        if self.use_longids:
            self.block_sizes["id"] = size*2
        else:
            self.block_sizes["id"] = size
        self.block_sizes["mass"] = size_mass
        self.block_sizes["u"] = size_gas
        self.block_sizes["rho"] = size_gas
        if self.flags["cooling"]:
            self.block_sizes["ne"] = size_gas
            self.block_sizes["nh"] = size_gas
        self.block_sizes["hsml"] = size_gas
        if self.flags["sfr"]:
            self.block_sizes["sfr"] = size_gas
        if self.flags["stellar_age"]:
            self.block_sizes["age"] = size_stars
        if self.flags["metals"]:
            self.block_sizes["metals"] = size_metals
        if self.flags["pot"]:
            self.block_sizes["pot"] = size
        if self.flags["accel"]:
            self.block_sizes["accel"] = size_space
        if self.flags["endt"]:
            self.block_sizes["endt"] = size_gas
        if self.flags["tstp"]:
            self.block_sizes["tstp"] = size
        if self.flags["feedback"]:
            self.block_sizes["esn"] = size_baryons
            self.block_sizes["esncold"] = size_baryons

    def _file_check(self):
        """Check the file structure for potential errors.

        Raises:
            NameError:  If block limits do not not match expected size.
        """

        s = self.swap

        f = open(self.name, 'rb')

        for key in self.block_keys:
            if key in self.block_sizes.keys():
                size = self.block_sizes[key]

                if size > 0.0:
                    data = f.read(4)
                    size_check = unpack(s+'I', data)[0]

                    if (size_check != size):
                        raise NameError("Error in block: %s" % key)

                    f.seek(size, 1)

                    data = f.read(4)
                    size_check = unpack(s+'I', data)[0]

                    if (size_check != size):
                        raise NameError("Error in block: %s" % key)

        f.close()

    def read_block(self, block_type, particle_type, iter_files=False):
        """Read block from snapshot file

        Args:
            block_type (str):   Type of block.
            particle_type (str): Type of particle.

        Returns:
            Panda DataFrame containing the block data for the specified
            particle type, indexed by particles ids

            The columns in the DataFrame are determined by the block type.
            In the case of 'pos', 'vel' and 'accel' blocks, columns are 'x',
            'y' and 'z'. For the 'metals' block, column names correspond to
            each elemet_type.
            All other blocks return a 1-column DataFrame named after the
            block_type.

        Raises:
            NameError:  If block limits do not not match expected size.

        Note:
            This functions only works for data blocks, to access header
            information use the `Simulation` class attributes.
        """

        if iter_files:
            return self.read_block_iter(block_type, particle_type)

        s = self.swap

        self._read_header()

        with open(self.name, 'rb') as f:

            size = self.block_sizes[block_type]

            order = self.block_keys.index(block_type)

            skip = 0
            for key in self.block_keys[0:order]:
                try:
                    skip += self.block_sizes[key] + 8
                except:
                    pass

            f.seek(skip, 0)

            data = f.read(4)
            size_check = unpack(s+'I', data)[0]
            if (size_check != size):
                raise NameError("Error reading block: %s" % block_type)

            offset, read_size, remainder = self._compute_offset(block_type,
                                                                particle_type)

            f.seek(offset, 1)

            data_block = f.read(read_size)

            f.seek(remainder, 1)

            data = f.read(4)
            size_check = unpack(s+'I', data)[0]
            if (size_check != size):
                raise NameError("Error reading block: %s" % block_type)

        dtype = s+'f4'
        if (block_type in ["id"]):
            dtype = s+'u4'
            if self.use_longids:
                dtype = s+'u8'

        block = fromstring(data_block, dtype=dtype)

        ydim = self.particle_numbers[particle_type]
        if (block_type in ["pos", "vel", "acc"]):
            shape = (ydim, 3)
        elif (block_type in ["metals"]):
            dim = len(self.element_keys)
            shape = (ydim, dim)
        else:
            shape = block.shape

        block.shape = shape

        if block_type in ["pos", "vel", "accel"]:
            columns = ['x', 'y', 'z']
        elif block_type in ["metals"]:
            columns = element_keys
        else:
            columns = [block_type]

        if block_type != "id":
            ids = self.read_block("id", particle_type)
            final_block = pd.DataFrame(block, columns=columns,
                                       index=ids.values)
        else:
            final_block = pd.Series(block, name="id")

        # self.cache[cache_key] = final_block

        return final_block

    def read_block_iter(self, block_type, particle_type):
        for i in range(self.file_number):
            snap = copy(self)
            snap.name = snap.basename + ".%d" % i
            block = snap.read_block(block_type, particle_type)
            yield block

    def _compute_offset(self, block_type, particle_type):
        """Computes offsets from the beginning of the block to the desired
        particles. As well as the size of the section containing the desired
        particles and the size of the remaining portion of the block.

        Args:
            block_type (str):   Type of block.
            particle_type (str): Type of particle.

        Returns:
            (tuple):    (offset, read_size, remainder).
        """

        particle_number = {}

        dim = 1

        if block_type in ["id", "pos", "vel", "accel", "pot", "tstp"]:
            particle_number = self.particle_numbers
            if block_type in ["pos", "vel", "accel"]:
                dim = 3
            if block_type in ["id"] and self.use_longids:
                dim = 2

        elif block_type in ["u", "rho", "ne", "nh", "hsml", "sfr", "endt"]:
            for key in ["gas"]:
                particle_number[key] = self.particle_numbers[key]

        elif block_type in ["esn", "esncold", "metals"]:
            for key in ["gas", "stars"]:
                particle_number[key] = self.particle_numbers[key]
            if block_type in ["metals"]:
                dim = len(self.element_keys)

        elif block_type in ["mass"]:
            for key in self.particle_keys:
                if self.particle_mass[key] == 0:
                    if self.particle_numbers[key] != 0:
                        particle_number[key] = self.particle_numbers[key]

        elif block_type in ["age"]:
            for key in ["stars"]:
                particle_number[key] = self.particle_numbers[key]

        order = self.particle_keys.index(particle_type)
        offset = 0
        for key in self.particle_keys[0:order]:
            if key in particle_number:
                offset += particle_number[key]

        remainder = 0
        for key in self.particle_keys[order+1:]:
            if key in particle_number:
                remainder += particle_number[key]

        dim *= 4
        read_size = particle_number[particle_type] * dim
        offset *= dim
        remainder *= dim

        return offset, read_size, remainder

    def filter_by_ids(self, block_type, particle_type, ids=[]):
        """Return a block filtered by particle ids

        Args:
            block_type (str):   Type of block.
            particle_type (str): Type of particle.
            ids (iterable): list of ids to return

        Returns:
            Pandas DataFrame as returned by read_block
        """

        block = self.read_block(block_type, particle_type)

        return block.loc[ids].dropna()

    def set_units(self,
                  velocity_in_cm_per_s=1e5,
                  lenght_in_cm=3.085678e24,
                  mass_in_g=1.989e43):
        """Set gadget internal units

        Args:
            velocity_in_cm_per_s: unit velocity un cm/s
            lenght_in_cm: unit lenght in cm
            mass_in_g: unit mass in grams

        Note:
            Default values result in:
                - velocity units in km/s
                - lenght units in kpc/h
                - mass units in 1e10 * solMass/h
            Where H0 = 100 * h Km s^{-1} Mpc^{-1} is the Hubble constant
        """

        unit_velocity_in_cm_per_s = velocity_in_cm_per_s * u.cm / u.s
        unit_lenght_in_cm = lenght_in_cm * u.cm
        unit_mass_in_g = mass_in_g * u.gram

        h = self.h
        vel = u.def_unit("gadget_velocity",
                         unit_velocity_in_cm_per_s.to("km/s"))
        lenght = u.def_unit("gadget_lenght", unit_lenght_in_cm.to("kpc") / h)
        mass = u.def_unit("gadget_mass", unit_mass_in_g.to("solMass") / h)
        time = lenght/vel

        self.gadget_velocity = vel
        self.gadget_lenght = lenght
        self.gadget_mass = mass
        self.gadget_time = time
        self.gadget_sfr = mass / time

    def __repr__(self):

        first = '<'
        last = '>'
        delimiter = ' | '

        string = first + self.name + delimiter
        for key in self.particle_keys:
            string += key + ': ' + '%d ' % self.particle_numbers[key]
        string += last

        return string

    def __str__(self):

        string = "file: %s\n" % self.name
        string += "file number: %s\n" % self.file_number
        string += "endianess: %s\n" % self.swap
        string += "particle numbers: %s\n" % self.particle_numbers
        string += "particle mass: %s\n" % self.particle_mass
        string += "cosmic time: %s\n" % self.cosmic_time
        string += "redshift: %s\n" % self.redshift
        string += "box size: %s\n" % self.box_size
        string += "omega_matter: %s\n" % self.omega_matter
        string += "omega_lambda: %s\n" % self.omega_lambda
        string += "h: %s\n" % self.h
        string += "flags: %s" % self.flags

        return string


class Fof:

    def __init__(self, basedir, num, snap=None):
        self.basedir = basedir
        self.num = num

        self.name = basedir
        self.name += "/groups_{0:03d}/group_tab_{0:03d}.0".format(self.num)

        self._read_header()
        self._load_catalogue()
        self._load_ids()

        self.snap = snap

    def _read_header(self):

        header_keys = [
            "totngroups",
            "ntask",
        ]
        with open(self.name, 'rb') as f:

            f.seek(8, 0)
            for key in header_keys:
                value = fromfile(f, dtype="i4", count=1)[0]
                setattr(self, key, value)

    def _load_catalogue(self):

        basename = self.basedir
        basename += "/groups_{0:03d}/group_tab_{0:03d}.".format(self.num)

        dims = 3
        n_particle_types = len(particle_keys)

        array_keys = [
            "grouplen",
            "groupoffset",
            "grouplentype",
            "groupmasstype",
            "groupcm",
            "groupsfr",
        ]

        self.ngroups = []
        self.nids = []
        totngroups = 0
        value = {}
        for i in range(self.ntask):
            name = basename + "{0:d}".format(i)
            with open(name, 'rb') as f:

                ngroups = fromfile(f, dtype="i4", count=1)[0]
                self.ngroups.append(ngroups)

                nids = fromfile(f, dtype="i4", count=1)[0]
                self.nids.append(nids)

                f.seek(2*4, 1)

                data_types = {
                    "grouplen": "({0},)i4".format(ngroups),
                    "groupoffset": "({0},)i4".format(ngroups),
                    "grouplentype": "({0},{1})i4".format(ngroups,
                                                         n_particle_types),
                    "groupmasstype": "({0},{1})f8".format(ngroups,
                                                          n_particle_types),
                    "groupcm": "({0},{1})f4".format(ngroups, dims),
                    "groupsfr": "({0},)f4".format(ngroups),
                }

                if ngroups > 0:
                    for key in array_keys:
                        dt = data_types[key]
                        data = fromfile(f, dtype=dt, count=1)[0]

                        if totngroups == 0:
                            value[key] = data
                        else:
                            value[key] = concatenate([value[key], data])
                    totngroups += ngroups

        for key in array_keys:
            setattr(self, key, value[key])

    def _load_ids(self):
        basename = self.basedir
        basename += "/groups_{0:03d}/group_ids_{0:03d}.".format(self.num)

        self.ids = []
        group = 0
        for i in range(self.ntask):
            name = basename + "{0}".format(i)
            with open(name, 'rb') as f:
                f.seek(4*4, 0)
                for j in range(self.ngroups[i]):
                    ids = {}
                    for p_type_n, particle_type in enumerate(particle_keys):
                        count = self.grouplentype[group, p_type_n]
                        ids[particle_type] = fromfile(f, dtype="u4",
                                                      count=count)
                    self.ids.append(ids)
                    group += 1

    def read_block_by_group(self, block_type, particle_type, group):
        ids = self.ids[group][particle_type]
        block = self.snap.filter_by_ids(block_type, particle_type, ids)

        return block


class Subfind:

    """ Base class for  handling subfind output

    Attributes:
        basedir (str): Base directory for subfind output
        basename (str): Base name for subfind output
        num (int): Number of subfind output
        snap (Simulation): Associated Simulation object
        ngroups (int): Number of halos
        nsubhalos (int): Number of subhalos
        nids (int): Number of particles
        ids (list): List containing arrays with ids for particles in each
                    subhalo
        nsubperhalo (array): Number of subhalos per halo
        firstsubofhalo (array): First subhalo index per halo
        sublen (array): Size of each subhalo
        suboffset (array): Offset index from the beginning for each subhalo
        subparenthalo (array): Parent halo of each subhalo
        halo_m_mean200 (array):
        halo_r_mean200 (array):
        halo_m_crit200 (array):
        halo_r_crit200 (array):
        halo_m_tophat200 (array):
        halo_r_tophat200 (array):
        subpos (2d array): Subhalo position
        subvel (2d array): Subhalo velocities
        subveldisp (2d array): Subhalo velocity dispersions
        subvmax (2d array): Subhalo maximum velocity
        subspin (2d array): Subhalo spin
        submostboundid (array): Subhalo id for most bound particle
        subhalfmass (array): Half mass of each subhalo
    """

    def __init__(self, basedir, num, snap=None):
        """Subfind initialization

        Args:
            basedir: Subfind base directory
            num: Subfind number
            snap: Associated Simulation object
        """

        self.basedir = basedir + "/postproc_{0:03d}/".format(num)
        self.num = num
        self.snap = snap

        self.basename = basedir
        self.basename += "/postproc_{0:03d}/sub_tab_{0:03d}.".format(self.num)

        folder = "/postproc_{0:03d}/".format(self.num)
        self.locationsname = basedir + folder + "locations.h5"

        self._read_header()
        self._load_catalogue()
        self._load_ids()

    def _read_header(self):
        """Read subfind header. Store ngrous, nids and nsubhalos"""

        name = self.basedir + "sub_tab_{0:03d}.{1}".format(self.num, 0)

        self.ngroups = []
        self.nids = []
        header_keys = [
            "totngroups",
            "ntask",
        ]
        self.nsubhalos = []
        with open(name, 'rb') as f:
            f.seek(8, 0)
            for key in header_keys:
                value = fromfile(f, dtype="i4", count=1)[0]
                setattr(self, key, value)

        self.ntask = 1

        for i in range(self.ntask):
            name = self.basename + "{0}".format(i)

            with open(name, 'rb') as f:
                f.seek(0, 0)
                value = fromfile(f, dtype="i4", count=1)[0]
                self.ngroups.append(value)

                value = fromfile(f, dtype="i4", count=1)[0]
                self.nids.append(value)

                f.seek(8, 1)

                value = fromfile(f, dtype="i4", count=1)[0]
                self.nsubhalos.append(value)

    def _load_catalogue(self):
        """Loads subfind catalogue"""

        array_keys = [
            "nsubperhalo",
            "firstsubofhalo",
            "sublen",
            "suboffset",
            "subparenthalo",
            "halo_m_mean200",
            "halo_r_mean200",
            "halo_m_crit200",
            "halo_r_crit200",
            "halo_m_tophat200",
            "halo_r_tophat200",
            "subpos",
            "subvel",
            "subveldisp",
            "subvmax",
            "subspin",
            "submostboundid",
            "subhalfmass",
        ]

        dims = 3
        value = {}
        for i in range(self.ntask):
            name = self.basedir + "sub_tab_{0:03d}.{1}".format(self.num, i)
            ngroups = self.ngroups[i]
            nsubhalos = self.nsubhalos[i]

            data_types = {
                "nsubperhalo": "({0},)i4".format(ngroups),
                "firstsubofhalo": "({0},)i4".format(ngroups),

                "sublen": "({0},)i4".format(nsubhalos),
                "suboffset": "({0},)i4".format(nsubhalos),
                "subparenthalo": "({0},)i4".format(nsubhalos),

                "halo_m_mean200": "({0},)f4".format(ngroups),
                "halo_r_mean200": "({0},)f4".format(ngroups),
                "halo_m_crit200": "({0},)f4".format(ngroups),
                "halo_r_crit200": "({0},)f4".format(ngroups),
                "halo_m_tophat200": "({0},)f4".format(ngroups),
                "halo_r_tophat200": "({0},)f4".format(ngroups),

                "subpos": "({0},{1})f4".format(nsubhalos, dims),
                "subvel": "({0},{1})f4".format(nsubhalos, dims),
                "subspin": "({0},{1})f4".format(nsubhalos, dims),

                "subveldisp": "({0},)f4".format(nsubhalos),
                "subvmax": "({0},)f4".format(nsubhalos),
                "subhalfmass": "({0},)f4".format(nsubhalos),

                "submostboundid": "({0},)i8".format(nsubhalos),
            }
            with open(name, 'rb') as f:
                f.seek(5*4, 0)
                for key in array_keys:
                    dt = data_types[key]
                    data = fromfile(f, dtype=dt, count=1)[0]

                    if i == 0:
                        value[key] = data
                    else:
                        value[key] = concatenate([value[key], data])

        for key in array_keys:
            setattr(self, key, value[key])

    def _load_ids(self):
        """Populates the ids list attribute with id arrays for particles
        in each subhalo
        """
        basename = self.basedir
        basename += "sub_ids_{0:03d}.".format(self.num)

        for i in range(self.ntask):
            name = basename + "{0}".format(i)
            with open(name, 'rb') as f:
                f.seek(4*4, 0)
                nids = self.nids[i]
                ids = fromfile(f, dtype="i8", count=nids)
            if i == 0:
                all_ids = ids
            else:
                all_ids = concatenate(self.ids, ids)

        self.ids = []
        for sub in range(self.nsubhalos[0]):
            nmin = self.suboffset[sub]
            nmax = nmin + self.sublen[sub]
            self.ids.append(all_ids[nmin:nmax])

    def read_block_by_subhalo(self, block_type, particle_type, subhalo,
                              sorter=[]):
        """Read snapshot block  filtered by subhalo

        Args:
            block_type (str):   Type of block.
            particle_type (str): Type of particle.
            subhalo (int): number of subhalo to read

        Returns:
            Pandas DataFrame as returned by read_block
        """

        block = self.snap.read_block(block_type, particle_type)

        sub_ids = self.ids[subhalo]

        fb, sorter = filter_bloc_by_ids(block, sub_ids, sorter)

        return fb, sorter

    def optical_radius(self, subhalo, factor=0.83):
        """Compute optical radius for a given subhalo

        Args:
            subhalo: subhalo
            factor (default = 0.83): mass factor to multiply the total mass.

        Returns:
            Optical radius in gadget internal Units.
            If no baryons are present returns 0.0
        """

        cm = self.subpos[subhalo]

        stars = False
        gas = False

        try:
            pos_stars, sorter = self.read_block_by_subhalo("pos",
                                                           "stars",
                                                           subhalo)
            mass_stars, sorter = self.read_block_by_subhalo("mass",
                                                            "stars",
                                                            subhalo,
                                                            sorter)
            stars = True
        except:
            pass

        try:
            pos_gas, sorter = self.read_block_by_subhalo("pos",
                                                         "gas",
                                                         subhalo,
                                                         sorter)
            mass_gas, sorter = self.read_block_by_subhalo("mass",
                                                          "gas",
                                                          subhalo,
                                                          sorter)
            gas = True
        except:
            pass

        if (stars and gas):
            pos = concatenate([pos_stars, pos_gas])
            mass = concatenate([mass_stars, mass_gas])
        elif (stars):
            pos = concatenate([pos_stars])
            mass = concatenate([mass_stars])
        elif (gas):
            pos = concatenate([pos_gas])
            mass = concatenate([mass_gas])

        h = self.snap.h
        kpc_h = u.def_unit("kpc_h", u.kpc / h)
        solMass_h = u.def_unit("solMass", u.solMass / h)
        gadget_mass = self.snap.gadget_mass
        gadget_lenght = self.snap.gadget_lenght

        rcut_high = 30 * kpc_h
        rcut_low = 50 * kpc_h
        mass_cut = 0.123480 * 1e10 * solMass_h

        total_mass = mass.sum() * gadget_mass
        if total_mass <= mass_cut:
            rcut = rcut_low * sqrt(total_mass/(1e10 * solMass_h))
        else:
            rcut = rcut_high
        rcut = rcut.to(gadget_lenght).value

        if (mass.size == 0):
            return 0.0

        r = sqrt(((pos-cm)**2).sum(axis=1))

        sort_ind = r.argsort()
        sort_r = r[sort_ind]
        sort_mass = mass[sort_ind]
        total_mass = sort_mass.cumsum()

        rcut_ind = searchsorted(sort_r, rcut) - 1

        mcut = total_mass[rcut_ind]
        mass_factor = factor * mcut

        ropt_ind = searchsorted(total_mass, mass_factor) - 1

        return sort_r[ropt_ind]

    def mass_inside_radius(self, radius, subhalo, particle_keys=particle_keys):
        """Compute subhalo mass inside a given radius

        Args:
            radius: radius in Gadget internal units
            subhalo: subhalo number
            particle_keys (optional): list containing particles types for witch
            to compute the mass

        Returns:
            Dictionary containing mass inside radius for each particle
            type specified in particle_keys
        """

        mass_inside = {}
        total_mass_inside = 0
        cm = self.subpos[subhalo]
        for key in particle_keys:
            try:
                pos = self.read_block_by_subhalo("pos", key, subhalo).values
                mass = self.read_block_by_subhalo("mass", key, subhalo).values

                r = sqrt(((pos-cm)**2).sum(axis=1))

                sort_ind = r.argsort()
                sort_r = r[sort_ind]
                sort_mass = mass[sort_ind]
                total_mass = sort_mass.cumsum()

                rcut_ind = searchsorted(sort_r, radius) - 1
                key_mass = total_mass[rcut_ind]
                mass_inside[key] = key_mass
                total_mass_inside += key_mass
            except KeyError:
                pass

        mass_inside['total'] = total_mass_inside
        return mass_inside

    def stellar_mass_below_thresholds(self, age_threshold,
                                      metallicity_threshold,
                                      subhalo,
                                      sorter=[],
                                      correct_metals=False):
        """Compute mass of stars with age below a certain threshold

        Args:
            age_threshold: Age threshold in yrs
            subhalo: subhalo number

        Returns:
            Mass in internal gadget units
        """

        stellar_age = age(self.read_block_by_subhalo("age", "stars",
                          subhalo, sorter)[0].values)
        stellar_age -= age(self.snap.cosmic_time)
        stellar_mass = self.read_block_by_subhalo("mass", "stars",
                                                  subhalo, sorter)[0]

        stellar_metallicity = self.read_block_by_subhalo("metals", "stars",
                                                         subhalo, sorter)[0]

        if correct_metals:
            stellar_metallicity = metallicity_corrected(stellar_metallicity,
                                                        self.snap.redshift)
        else:
            stellar_metallicity = metals_tometal(stellar_metallicity,
                                                 stellar_mass).values
            stellar_metallicity = stellar_metallicity / 0.02

        isyoung = stellar_age < age_threshold
        isyoung = isyoung.flatten()

        ismetal = stellar_metallicity < metallicity_threshold
        ismetal = ismetal.flatten()

        isdet = isyoung * ismetal

        isabove = isyoung * ~ismetal

        return stellar_mass.values[isdet].sum(), stellar_mass.values[isabove].sum()

    def stellar_mass_above_thresholds(self, age_threshold,
                                      metallicity_threshold,
                                      subhalo,
                                      sorter=[],
                                      correct_metals=False):
        """Compute mass of stars with age below a certain threshold

        Args:
            age_threshold: Age threshold in yrs
            subhalo: subhalo number

        Returns:
            Mass in internal gadget units
        """

        stellar_age = age(self.read_block_by_subhalo("age", "stars",
                          subhalo, sorter)[0].values)
        stellar_age -= age(self.snap.cosmic_time)
        stellar_mass = self.read_block_by_subhalo("mass", "stars",
                                                  subhalo, sorter)[0]

        stellar_metallicity = self.read_block_by_subhalo("metals", "stars",
                                                         subhalo, sorter)[0]

        if correct_metals:
            stellar_metallicity = metallicity_corrected(stellar_metallicity,
                                                        self.snap.redshift)
        else:
            stellar_metallicity = metals_tometal(stellar_metallicity,
                                                 stellar_mass).values
            stellar_metallicity = stellar_metallicity / 0.02

        isyoung = stellar_age < age_threshold
        isyoung = isyoung.flatten()

        ismetal = stellar_metallicity > metallicity_threshold
        ismetal = ismetal.flatten()

        isdet = isyoung * ismetal

        return stellar_mass.values[isdet].sum()

    def __repr__(self):

        first = '<'
        last = '>'
        delimiter = ' | '

        nsubhalos = self.nsubhalos[0]
        nids = self.nids[0]

        string = first + self.basedir + delimiter
        string += "nsubhalos: {nsubhalos}" + delimiter + "nids: {nids}"
        string += last
        string = string.format(nsubhalos=nsubhalos, nids=nids)

        return string


def filter_bloc_by_ids(block, ids, sorter=[]):
    """ return block filter by ids

    Args:
        block: Simulation block
        ids (array like): list of ids
        sorter (optional array-like): list of postions that sort
                                      the block ids, greatly improves speed
    """
    ind = block.index.values

    sorter = array(sorter)
    if sorter.size == 0:
        sorter = ind.argsort()

    ids = ids[ids <= ind.max()]

    i = ind.searchsorted(ids, sorter=sorter)
    i = unique(i)

    df = block.iloc[sorter[i]]
    df = df.loc[ids].dropna()

    return df, sorter


def bounding_box(block_pos, ids, sorter=[], padding=[0, 0, 0]):
    """ Compute bounding box limits, center and extent.

    Returns a dictionary

    Args:
        block_pos: Simulation postion block
        ids (array like): list of ids
        sorter (optional array-like): list of postions that sort
                                      the block ids, greatly improves spped
        padding (optional array-like): padding to add to the minimum bounding
                                       box
    """

    df = filter_bloc_by_ids(block_pos, ids, sorter)
    xlims = [df.x.min() - padding[0], df.x.max() + padding[0]]
    ylims = [df.y.min() - padding[1], df.y.max() + padding[1]]
    zlims = [df.z.min() - padding[2], df.z.max() + padding[2]]

    xcen = (xlims[0] + xlims[1])/2
    ycen = (ylims[0] + ylims[1])/2
    zcen = (zlims[0] + zlims[1])/2

    xext = xlims[1] - xlims[0]
    yext = ylims[1] - ylims[0]
    zext = zlims[1] - zlims[0]

    bounding_box = {}

    bounding_box['limits'] = [xlims, ylims, zlims]
    bounding_box['center'] = [xcen, ycen, zcen]
    bounding_box['extent'] = [xext, yext, zext]

    return bounding_box


def region(block_pos, x0=[0, 0, 0], dx=[10, 10, 10]):
    x0 = array(x0)
    dx = array(dx)

    xmax = x0 + dx
    xmin = x0 - dx

    df = block_pos[
                    (block_pos.x < xmax[0]) &
                    (block_pos.x > xmin[0]) &
                    (block_pos.y < xmax[1]) &
                    (block_pos.y > xmin[1]) &
                    (block_pos.z < xmax[2]) &
                    (block_pos.z > xmin[2])
                   ]

    return df


def metals_tometal(metals, mass):
    m = metals.sum(axis=1)
    m = m - metals["He"] - metals["H"]
    v = m.values
    v.shape = (v.size, 1)
    v = v / mass.values
    result = pd.DataFrame(index=metals.index)
    result["metals"] = v
    return result


def metallicity_corrected(metals, redshift, a=-0.418357126827,
                          b=0.568664243551, filtered=False):
    """Return metallicity corrected

    Args:
        metals: Pandas DataFrame as returned by Simulation.read_block
        redshift: Pandas DataFrame as returned by Simulation.read_block
        a: correction parameter a
        b: correction parameter b

    Returns:
        Corrected metallicity in units of solar metallicity

    Note:
        The assumed correction is
        [12 + log(O/H)]' = 12 + log(O/H) + a*z + b
    """

    O_ab_sun = 8.69
    O_abundance = 12.0 + np.log10(metals.O / (16 * metals.H))

    metallicity = O_abundance.values + (a*redshift + b) - O_ab_sun
    data_nc = O_abundance.values - O_ab_sun

    result = 10**metallicity

    data = result

    if filtered:
        for i, value in enumerate(data):
            if value > 2:
                data[i] = 10**data_nc[i]

    return data