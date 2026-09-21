import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import {Alert} from 'react-native';
import {CircleDiscovery} from '../src/CircleDiscovery';
import {changeMemberCircle, listMemberCircles} from '../src/memberSession';

jest.mock('../src/memberSession', () => ({
  changeMemberCircle: jest.fn(),
  listMemberCircles: jest.fn(),
}));

const id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const available = {id, name: 'Music', description: 'Listen together', active: true,
  joined: false, suggested: true};

beforeEach(() => {
  jest.clearAllMocks();
  (listMemberCircles as jest.Mock).mockResolvedValue([available]);
  (changeMemberCircle as jest.Mock).mockResolvedValue(undefined);
});

test('shows a suggested circle and joins using the member account', async () => {
  let screen!: ReactTestRenderer.ReactTestRenderer;
  await ReactTestRenderer.act(async () => {
    screen = ReactTestRenderer.create(<CircleDiscovery language="en" />);
  });
  expect(JSON.stringify(screen.toJSON())).toContain('Suggested');
  expect(JSON.stringify(screen.toJSON())).toContain('Music');
  const join = screen.root.findAllByProps({accessibilityRole: 'button'})[0];
  await ReactTestRenderer.act(async () => join.props.onPress());
  expect(changeMemberCircle).toHaveBeenCalledWith(id, true);
});

test('asks before leaving a joined circle', async () => {
  (listMemberCircles as jest.Mock).mockResolvedValue([{...available, joined: true}]);
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  let screen!: ReactTestRenderer.ReactTestRenderer;
  await ReactTestRenderer.act(async () => {
    screen = ReactTestRenderer.create(<CircleDiscovery language="en" />);
  });
  const leave = screen.root.findAllByProps({accessibilityRole: 'button'})[0];
  await ReactTestRenderer.act(async () => leave.props.onPress());
  expect(alert).toHaveBeenCalled();
  expect(changeMemberCircle).not.toHaveBeenCalled();
  alert.mockRestore();
});

test('explains the membership limit instead of pretending a join succeeded', async () => {
  (changeMemberCircle as jest.Mock).mockRejectedValue({code: 'CIRCLE_LIMIT'});
  let screen!: ReactTestRenderer.ReactTestRenderer;
  await ReactTestRenderer.act(async () => {
    screen = ReactTestRenderer.create(<CircleDiscovery language="en" />);
  });
  const join = screen.root.findAllByProps({accessibilityRole: 'button'})[0];
  await ReactTestRenderer.act(async () => join.props.onPress());
  expect(JSON.stringify(screen.toJSON())).toContain('reached the circle limit');
});
