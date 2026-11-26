import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:lectio_mobile/main.dart';

Future<void> _pumpAt(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  await tester.pumpWidget(const LectioApp());
  await tester.pump();
}

void main() {
  testWidgets('Landing screen lays out on a phone', (tester) async {
    await _pumpAt(tester, const Size(390, 844));
    expect(tester.takeException(), isNull);
    expect(find.text('Try now'), findsOneWidget);
  });

  testWidgets('Landing screen lays out on desktop width', (tester) async {
    await _pumpAt(tester, const Size(1280, 800));
    expect(tester.takeException(), isNull);
    expect(find.text('Try now'), findsOneWidget);
  });
}
