/**
 * @format
 */

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import App from '../App';

jest.mock('react-native-safe-area-context', () => ({
  SafeAreaProvider: ({children}: {children: React.ReactNode}) => children,
  useSafeAreaInsets: () => ({top: 0, bottom: 0, left: 0, right: 0}),
}));

test('renders correctly', async () => {
  await ReactTestRenderer.act(() => {
    ReactTestRenderer.create(<App />);
  });
});

test('switches between the three core areas and Bengali/Hindi navigation', async () => {
  let screen!: ReactTestRenderer.ReactTestRenderer;
  await ReactTestRenderer.act(() => {
    screen = ReactTestRenderer.create(<App />);
  });

  const press = async (props: Record<string, unknown>) => {
    const control = screen.root.findByProps(props);
    await ReactTestRenderer.act(() => control.props.onPress());
  };
  const visibleText = () => JSON.stringify(screen.toJSON());

  expect(visibleText()).toContain('Good to see you');
  await press({testID: 'tab-circles'});
  expect(visibleText()).toContain('Find your circle');
  await press({accessibilityLabel: 'Language: বাংলা'});
  expect(visibleText()).toContain('আপনার দল খুঁজুন');
  await press({accessibilityLabel: 'ভাষা: हिन्दी'});
  expect(visibleText()).toContain('अपना समूह खोजें');
  await press({testID: 'tab-profile'});
  expect(visibleText()).toContain('आपकी प्रोफ़ाइल');
});
