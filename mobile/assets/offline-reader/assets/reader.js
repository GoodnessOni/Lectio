(function () {
  'use strict';
  var root = document.getElementById('lectio-manifest');
  var data;
  try { data = JSON.parse(root.textContent); }
  catch (error) { document.getElementById('lecture-title').textContent = 'Study pack could not be read'; return; }
  var lecture = data.lecture || data;
  var $ = function (id) { return document.getElementById(id); };
  var segmentById = {};
  (lecture.transcript && lecture.transcript.segments || []).forEach(function (segment) { segmentById[segment.id] = segment; });
  $('lecture-title').textContent = lecture.title || 'Untitled lecture';
  $('lecture-meta').textContent = [lecture.courseCode, lecture.lectureDate ? 'Date ' + lecture.lectureDate : '', 'Revision ' + (lecture.revision || 0)].filter(Boolean).join('. ');
  $('revision-label').textContent = 'Revision ' + (lecture.revision || 0);
  var selected = (lecture.recordings || []).find(function (r) { return r.id === (lecture.selection || {}).recordingId; });
  var audioPath = selected && selected.audioUrl && !selected.audioUrl.match(/^https?:|^\//) ? selected.audioUrl : null;
  if (audioPath) {
    $('audio-section').hidden = false;
    $('lecture-audio').src = audioPath;
    $('audio-label').textContent = selected.fileName || 'Original recording';
    $('media-notice').textContent = 'This pack contains a local audio file. No network request is needed.';
  } else {
    $('media-notice').textContent = 'This study pack contains notes, a transcript and practice questions. No source audio file was supplied, so playback is not included.';
  }
  function jump(id) {
    var segment = segmentById[id];
    if (!segment) return;
    document.querySelectorAll('.segment').forEach(function (item) { item.classList.toggle('active', item.getAttribute('data-id') === id); });
    if (!$('audio-section').hidden) {
      $('lecture-audio').currentTime = segment.startSec || 0;
      $('lecture-audio').play().catch(function () {});
    }
    $('transcript').scrollIntoView({ behavior:'smooth', block:'start' });
  }
  var notes = lecture.notes && lecture.notes.sections || [];
  $('notes').innerHTML = notes.length ? notes.map(function (note, index) {
    var steps = note.steps && note.steps.length ? '<ol>' + note.steps.map(function (s) { return '<li>' + escapeHtml(s) + '</li>'; }).join('') + '</ol>' : '';
    var sources = (note.sourceSegmentIds || []).map(function (id) { var seg = segmentById[id]; return '<button class="source" data-id="' + escapeAttr(id) + '">Open source at ' + (seg ? time(seg.startSec) : '') + '</button>'; }).join('');
    return '<article class="note"><div class="note-no">' + String(index + 1).padStart(2,'0') + '</div><div><h2>' + escapeHtml(note.heading) + '</h2><p>' + escapeHtml(note.body) + '</p>' + steps + sources + '</div></article>';
  }).join('') : '<p class="empty">No published notes in this pack.</p>';
  var segments = lecture.transcript && lecture.transcript.segments || [];
  $('transcript').innerHTML = segments.length ? segments.map(function (segment) { return '<button class="segment" data-id="' + escapeAttr(segment.id) + '"><small>' + time(segment.startSec) + ' to ' + time(segment.endSec) + '</small>' + escapeHtml(segment.text) + '</button>'; }).join('') : '<p class="empty">No transcript was included.</p>';
  var photos = lecture.photos || [];
  $('photos').innerHTML = photos.length ? photos.map(function (photo) {
    var src = photo.imageUrl && !photo.imageUrl.match(/^https?:|^\//) ? photo.imageUrl : '';
    return src ? '<figure class="photo"><img src="' + escapeAttr(src) + '" alt="' + escapeAttr(photo.caption || 'Lecture board photo') + '"/><figcaption>' + escapeHtml(photo.caption || photo.fileName || 'Board photo') + '. ' + time(photo.timestampSec) + '</figcaption></figure>' : '';
  }).join('') || '<p class="empty">No board photo files were included.</p>' : '<p class="empty">No board photo files were included.</p>';
  var questions = lecture.questions || [];
  $('questions').innerHTML = questions.length ? questions.map(function (question, index) {
    var choices = (question.choices || []).map(function (choice, choiceIndex) { return '<div class="choice">' + String.fromCharCode(65 + choiceIndex) + '. ' + escapeHtml(choice.text) + '</div>'; }).join('');
    var answer = (question.choices || []).find(function (choice) { return choice.id === question.answerId; });
    var source = (question.sourceSegmentIds || []).map(function (id) { return '<button class="source" data-id="' + escapeAttr(id) + '">Open source at ' + (segmentById[id] ? time(segmentById[id].startSec) : '') + '</button>'; }).join('');
    return '<article class="question"><h3>' + String(index + 1) + '. ' + escapeHtml(question.prompt) + '</h3>' + choices + '<p class="answer">Answer: ' + escapeHtml(answer ? answer.text : question.answerId) + '<br/><span>' + escapeHtml(question.explanation) + '</span></p>' + source + '</article>';
  }).join('') : '<p class="empty">No practice questions were included.</p>';
  document.addEventListener('click', function (event) { var button = event.target.closest('[data-id]'); if (button) jump(button.getAttribute('data-id')); });
  function time(sec) { sec = Math.max(0, Math.floor(Number(sec) || 0)); return String(Math.floor(sec/60)).padStart(2,'0') + ':' + String(sec%60).padStart(2,'0'); }
  function escapeHtml(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) { return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]); }); }
  function escapeAttr(value) { return escapeHtml(value); }
})();
