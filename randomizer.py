from randomtools.tablereader import (
    TableObject, get_global_label, tblpath, addresses, get_random_degree,
    get_activated_patches, mutate_normal, shuffle_normal, write_patch)
from randomtools.utils import (
    classproperty, cached_property, get_snes_palette_transformer,
    read_multi, write_multi, utilrandom as random)
from randomtools.interface import (
    get_outfile, get_seed, get_flags, get_activated_codes, activate_code,
    run_interface, rewrite_snes_meta, clean_and_write, finish_interface)
from randomtools.itemrouter import ItemRouter, ItemRouterException
from collections import defaultdict
from os import path
from time import time, sleep, gmtime
from collections import Counter
from itertools import combinations


VERSION = 1
FIST = 0x44d

assigned_pointers = {}


class ChestObject(TableObject):
    def cleanup(self):
        assert 0x44e <= self.item <= 0x474 or self.item <= 5
        assert (0x44e <= self.old_data['item'] <= 0x474
                or self.old_data['item'] <= 5)


class EventChestObject(TableObject):
    def cleanup(self):
        assert FIST <= self.item <= 0x474
        assert FIST <= self.old_data['item'] <= 0x474


class EventMemoryObject(TableObject):
    @property
    def chest(self):
        chests = [c for c in EventChestObject
                  if c.old_data['item'] == self.old_data['item']]
        assert len(chests) == 1
        return chests[0]

    def cleanup(self):
        self.item = self.chest.item
        assert FIST <= self.item <= 0x474
        assert FIST <= self.old_data['item'] <= 0x474


class EventMessageObject(TableObject):
    @property
    def chest(self):
        chests = [c for c in EventChestObject
                  if c.old_data['item'] == self.old_data['code'] + 0x44a]
        assert len(chests) == 1
        return chests[0]

    def cleanup(self):
        self.code = self.chest.item - 0x44a
        assert 0x3 <= self.code <= 0x2a
        assert 0x3 <= self.old_data['code'] <= 0x2a


class TechEntranceObject(TableObject):
    @property
    def old_exit(self):
        return TechExitObject.get(self.index)

    @property
    def map_conversions(self):
        return {0x47d: 5,
                0x47e: 4,
                0x47f: 3,
                }

    @property
    def new_map_code(self):
        if not hasattr(self, 'item'):
            assert assigned_pointers[addresses.bonus_item_address] >= 0x47d
            self.item = assigned_pointers[addresses.bonus_item_address]
        return self.map_conversions[self.item]

    def cleanup(self):
        self.map_code = self.new_map_code
        assert 3 <= self.map_code <= 5

    @classmethod
    def full_cleanup(cls):
        super(TechEntranceObject, cls).full_cleanup()
        assert set(teo.map_code for teo in TechEntranceObject) == set(
            teo.map_code for teo in TechEntranceObject)


class TechExitObject(TableObject):
    @property
    def old_entrance(self):
        return TechEntranceObject.get(self.index)

    @property
    def new_entrance(self):
        teos = [teo for teo in TechEntranceObject
                if teo.new_map_code == self.old_entrance.old_data['map_code']]
        assert len(teos) == 1
        return teos[0]

    def cleanup(self):
        self.x = self.new_entrance.old_exit.old_data['x']
        self.y = self.new_entrance.old_exit.old_data['y']
        assert self.old_data['byte_59'] == self.byte_59 == 0x59
        assert self.old_data['byte_5a'] == self.byte_5a == 0x5a

    @classmethod
    def full_cleanup(cls):
        super(TechExitObject, cls).full_cleanup()
        assert set((teo.x, teo.y) for teo in TechExitObject) == set(
            (teo.old_data['x'], teo.old_data['y']) for teo in TechExitObject)


def get_all_vanilla_items():
    return [c.item for c in ChestObject] + [c.item for c in EventChestObject]


def set_item_by_pointer(item, pointer):
    assert pointer not in assigned_pointers
    assert item <= 5 or item == FIST or item not in assigned_pointers.values()
    assigned_pointers[pointer] = item

    candidates = [c for c in ChestObject if c.pointer == pointer]
    if len(candidates) != 1:
        candidates = [c for c in EventChestObject if c.pointer == pointer]
    if len(candidates) != 1:
        candidates = [c for c in TechEntranceObject if c.pointer == pointer]
    if len(candidates) == 1:
        candidates[0].item = item
        return candidates[0]
    elif pointer == addresses.bonus_item_address:
        f = open(get_outfile(), 'r+b')
        f.seek(pointer)
        write_multi(f, item, length=2)
        f.close()
        return
    raise Exception('No suitable item location found: %x' % pointer)


def route_items():
    ChestObject.class_reseed('router')

    ir = ItemRouter(path.join(tblpath, 'requirements.txt'),
                    path.join(tblpath, 'restrictions.txt'))
    ir.assign_everything()
    for location, item in sorted(ir.assignments.items()):
        pointer = location.split('_')[-1]
        item, pointer = int(item, 0x10), int(pointer, 0x10)
        set_item_by_pointer(item, pointer)

    # assign health and magic upgrades
    health_magic = [c.old_data['item'] for c in ChestObject.every
                    if c.old_data['item'] <= 1]
    random.shuffle(health_magic)
    unused_chests = [c.pointer for c in ChestObject.every
                     if c.pointer not in assigned_pointers]
    random.shuffle(unused_chests)
    for item, pointer in zip(health_magic, unused_chests):
        location = [l for l in ir.unassigned_locations
                    if l.endswith('%x' % pointer)]
        assert len(location) == 1
        location = location[0]
        ir.assign_item_location('{0:0>4x}'.format(item), location)
        set_item_by_pointer(item, pointer)

    # assign unused equipment
    unused_uniques = [
        c.old_data['item'] for c in ChestObject.every + EventChestObject.every
        if c.old_data['item'] >= FIST
        and c.old_data['item'] not in assigned_pointers.values()]
    random.shuffle(unused_uniques)
    assert len(unused_uniques) == len(set(unused_uniques))
    for u in unused_uniques:
        try:
            item = '{0:0>4x}'.format(u)
            ir.assign_item(item, aggression=ir.aggression+1)
            location = ir.get_assigned_location(item)
            pointer = int(location.split('_')[-1], 0x10)
            set_item_by_pointer(u, pointer)
        except ItemRouterException:
            pass

    # assign cash
    cash = [c.old_data['item'] for c in ChestObject.every
            if 2 <= c.old_data['item'] <= 5]
    random.shuffle(cash)
    unused_chests = [c.pointer for c in ChestObject.every
                     if c.pointer not in assigned_pointers]
    random.shuffle(unused_chests)
    for item, pointer in zip(cash, unused_chests):
        set_item_by_pointer(item, pointer)

    # finish off the rest
    for c in ChestObject.every:
        if c.pointer not in assigned_pointers:
            set_item_by_pointer(5, c.pointer)
    for c in EventChestObject.every:
        if c.pointer not in assigned_pointers:
            set_item_by_pointer(FIST, c.pointer)
    #print ir.report


if __name__ == '__main__':
    try:
        print ('You are using the Super Adventure Island II '
               'randomizer version %s.' % VERSION)
        print

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]

        codes = {}

        run_interface(ALL_OBJECTS, snes=True, codes=codes, custom_degree=True)

        f = open(get_outfile(), 'r+b')
        f.seek(addresses.bonus_item_address)
        write_multi(f, FIST, length=2)
        f.close()

        route_items()

        clean_and_write(ALL_OBJECTS)
        rewrite_snes_meta('SAI2-R', VERSION, lorom=False)

        finish_interface()

    except Exception, e:
        print 'ERROR: %s' % e
        raw_input('Press Enter to close this program.')
