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
from sys import argv


VERSION = 1
FIST = 0x44d

assigned_pointers = {}


def get_open_code():
    s = ''
    if 'custom' in get_activated_codes():
        s += 'C'
    elif 'openworld' in get_activated_codes():
        s += 'W'
    elif 'openrandom' in get_activated_codes():
        s += 'R'
    else:
        s += 'S'
    v = "%s" % VERSION
    assert len(v) == 1
    s += v
    return s


def get_seed_with_code():
    seed_label = str(get_seed())
    seed_label += get_open_code()
    return seed_label


def write_seed_info():
    from string import uppercase, lowercase, digits
    seed_label = get_seed_with_code()
    assert len(seed_label) <= 12
    while len(seed_label) < addresses.seed_length:
        seed_label += ' '
    assert len(seed_label) == addresses.seed_length
    f = open(get_outfile(), 'r+b')
    f.seek(addresses.seed_write_addr)
    for c in seed_label:
        if c in digits:
            value = 0x01 + int(c)
        elif c in lowercase:
            value = lowercase.index(c) | 0x100
        elif c in uppercase:
            value = 0x19 + uppercase.index(c)
        elif c == ' ':
            value = 0x100
        else:
            raise Exception('Cannot write character %s.' % c)
        write_multi(f, value, length=2)
    f.close()


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
        self.x2 = self.new_entrance.old_exit.old_data['x2']
        self.y2 = self.new_entrance.old_exit.old_data['y2']
        assert self.old_data['byte_59'] == self.byte_59 == 0x59
        assert self.old_data['byte_5a'] == self.byte_5a == 0x5a
        assert self.old_data['byte_7a'] == self.byte_7a == 0x7a
        assert self.old_data['byte_7b'] == self.byte_7b == 0x7b

    @classmethod
    def full_cleanup(cls):
        super(TechExitObject, cls).full_cleanup()
        assert (set((teo.x, teo.y, teo.x2, teo.y2) for teo in TechExitObject)
                == set((teo.old_data['x'], teo.old_data['y'],
                        teo.old_data['x2'], teo.old_data['y2'])
                       for teo in TechExitObject))


def write_bonus_item(item):
    f = open(get_outfile(), 'r+b')
    f.seek(addresses.bonus_item_address)
    write_multi(f, item, length=2)
    f.seek(addresses.bonus_item_value_address)
    value = 1
    # protect Fist, No Armor, No Shield, and Do Not Use
    if item + 1 in [0x44d, 0x45a, 0x45f, 0x465]:
        value |= 0x100
    write_multi(f, value, length=2)
    f.close()


def set_item_by_pointer(item, pointer):
    assert pointer not in assigned_pointers
    #assert item <= 5 or item == FIST or item not in assigned_pointers.values()
    assert item <= 5 or FIST <= item <= 0x047f
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
        write_bonus_item(item)
        return
    raise Exception('No suitable item location found: %x' % pointer)


def route_items():
    ChestObject.class_reseed('gates')

    ir = ItemRouter(path.join(tblpath, 'requirements.txt'),
                    path.join(tblpath, 'restrictions.txt'))

    if 'custom' in get_activated_codes():
        custom_items = {}
        custom_filename = raw_input(
            'Please enter a filename for custom item assignments. ')
        f = open(custom_filename)
        for line in f:
            if '#' in line:
                index = line.index('#')
                line = line[:index]
            line = line.strip()
            while '  ' in line:
                line = line.replace('  ', ' ')
            line = line.strip()
            line = line.split()
            if len(line) == 2:
                location, item = line
                location = location.split('_')
                assert len(location) >= 2
                location = location[0] + '_' + location[-1]
                custom_items[location] = item
        ir.set_custom_assignments(custom_items)

    gates = ['light', 'sun', 'star', 'aqua', 'moon']
    for g in gates:
        if ('openworld' in get_activated_codes()
                or ('openrandom' in get_activated_codes()
                    and random.choice([True, False]))):
            print ('OPEN %s GATE' % g).upper()
            stone = '%sgate_down' % g
            assert stone in ir.assign_conditions
            ir.assign_conditions[stone] = '*'
            addr = '%s_gate_address' % g
            assert hasattr(addresses, addr)
            addr = getattr(addresses, addr)
            f = open(get_outfile(), 'r+b')
            f.seek(addr)
            f.write('\x00')
            f.close()

    ChestObject.class_reseed('router')
    ir.assign_everything()
    spoilers = ir.report
    for location, item in sorted(ir.assignments.items()):
        pointer = location.split('_')[-1]
        item, pointer = int(item, 0x10), int(pointer, 0x10)
        set_item_by_pointer(item, pointer)

    # assign health and magic upgrades
    num_life_bottles = 2
    if 'balance_patch.txt' in get_activated_patches():
        num_life_bottles += 2
    num_life_bottles += len([v for v in ir.assignments.values()
                             if int(v, 0x10) == 0])
    health_magic = [c.old_data['item'] for c in ChestObject.every
                    if c.old_data['item'] <= 1]
    while num_life_bottles + health_magic.count(0) > 14:
        health_magic.remove(0)
    num_magic_pots = 1
    num_magic_pots += len([v for v in ir.assignments.values()
                           if int(v, 0x10) == 1])
    while num_magic_pots + health_magic.count(0) > 14:
        health_magic.remove(1)

    unused_chests = [c.pointer for c in ChestObject.every
                     if c.pointer not in assigned_pointers]
    random.shuffle(health_magic)
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

    spoiler_filename = '{0}_spoilers.txt'.format(get_seed_with_code())
    f = open(spoiler_filename, 'w+')
    f.write('{0}\n\n'.format(get_seed_with_code()))
    f.write(spoilers + '\n')
    f.close()


if __name__ == '__main__':
    try:
        print ('You are using the Super Adventure Island II '
               'randomizer version %s.' % VERSION)
        print

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]

        codes = {'openworld': ['openworld'],
                 'openrandom': ['openrandom'],
                 'custom': ['custom'],
                 }

        run_interface(ALL_OBJECTS, snes=True, codes=codes, custom_degree=False)

        if len(argv) <= 2:
            print ('\nThe following codes are available.\n'
                   'openworld  : Start with all gates lowered.\n'
                   'openrandom : Start with random gates lowered.\n'
                   '\n'
                   'If you would like to use either of these codes, '
                   'type it here,')
            codes = raw_input('or just press enter to continue. ')
            for code in codes.split():
                if code.strip():
                    activate_code(code.strip())
            print '\n'

        write_bonus_item(FIST)
        route_items()

        write_seed_info()
        clean_and_write(ALL_OBJECTS)
        rewrite_snes_meta('SAI2-R', VERSION, lorom=False)

        finish_interface()

    except Exception, e:
        print 'ERROR: %s' % e
        raw_input('Press Enter to close this program. ')
